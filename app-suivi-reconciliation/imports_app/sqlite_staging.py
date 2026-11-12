"""Préparation isolée, staging invisible par lots et publication SQLite atomique.

La logique métier existante travaille sur une copie cohérente de la base. Seuls
les résultats vérifiés sont transférés. Les triggers de révision empêchent la
publication si un utilisateur modifie les données métier pendant ce calcul.
"""

import contextlib
import hashlib
import shutil
import sqlite3
import time
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

STAGED = (
    "reconciliation_campaigninventory",
    "reconciliation_campaigngroup",
    "reconciliation_multiplecontrol",
    "reconciliation_campaignsageentry",
    "reconciliation_campaignglobalcontrol",
    "reconciliation_accountinggroup",
    "reconciliation_accountingproject",
)
PROJECTED = (
    "projects_project",
    "reconciliation_reconciliationtransaction",
    "reconciliation_reviewgroup",
    "reconciliation_atlasadjustment",
    "reconciliation_manualreconciliation",
    "reconciliation_manualallocation",
    "reconciliation_campaignaction",
    "reconciliation_linereview",
    "reconciliation_reviewevent",
    "reconciliation_campaignreview",
    "reconciliation_reviewcontrolcontext",
    "reconciliation_controlcontribution",
)
CAMPAIGN = "reconciliation_campaign"
REVISION = "reconciliation_importrevision"
BATCH = 500
LABELS = dict(
    zip(STAGED, ("Inventaire", "Preuves des groupes", "Contrôles des multiples",
                 "Inventaire Sage", "Contrôles globaux", "Groupes de cadrage", "Synthèses de cadrage"), strict=True)
)


def is_file_sqlite():
    """Réserve ce circuit aux bases SQLite sur disque."""
    name = str(connection.settings_dict["NAME"])
    return connection.vendor == "sqlite" and name != ":memory:" and "mode=memory" not in name


def open_database(path):
    """Ouvre une connexion dédiée, en autocommit et avec contraintes référentielles actives."""
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    return db


def enable_wal(db):
    """Active WAL avant l'import, hors transaction ; aucun arrêt forcé d'un autre écrivain."""
    mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    if mode.lower() != "wal":
        raise ValidationError(
            "Impossible d’activer WAL ; arrêter les anciens imports avant de reprendre"
        )


def revision(db, schema="main"):
    """Lit le compteur transactionnel des mutations métier."""
    if not db.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (REVISION,)
    ).fetchone():
        raise ValidationError(
            "Migration de suivi des imports absente : exécuter prepare_sqlite_imports --migrate"
        )
    row = db.execute(f"SELECT revision FROM {schema}.{REVISION} WHERE id=1").fetchone()
    if row is None:
        raise ValidationError("Migration de suivi des imports absente : exécuter manage.py migrate")
    return row[0]


@contextlib.contextmanager
def write_batch(db, progress, phase, *, expected=None):
    """Prend le verrou d'écriture avant de lire, vérifie la fraîcheur et mesure sa durée."""
    start = time.monotonic()
    db.execute("BEGIN IMMEDIATE")
    try:
        if expected is not None and revision(db) != expected:
            raise ValidationError(
                "Une décision ou donnée métier a changé pendant la préparation. "
                "Aucune publication effectuée ; relancez l’import pour la prendre en compte."
            )
        yield
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    finally:
        progress(phase, transaction_seconds=round(time.monotonic() - start, 3))


def clear_unpublished(db, progress):
    """Nettoie les lots invisibles d'un import interrompu, enfants avant parents.

    Préserve les campagnes publiées ; l'ordre inverse protège les références
    des groupes de cadrage aux contrôles. Les écritures restent par lots atomiques.
    """
    # Une interruption pendant publication est annulée par SQLite ; les seules
    # traces possibles sont les tables de staging avec published=0.
    for table in reversed(STAGED):
        while True:
            with write_batch(db, progress, "Nettoyage des lots non publiés"):
                cursor = db.execute(
                    f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} "
                    f"WHERE campaign_id IN (SELECT id FROM {CAMPAIGN} WHERE published=0) LIMIT ?)",
                    (BATCH,),
                )
            if cursor.rowcount < BATCH:
                break
    with write_batch(db, progress, "Nettoyage des campagnes non publiées"):
        db.execute(f"DELETE FROM {CAMPAIGN} WHERE published=0")


def make_snapshot(db, path, progress):
    """Copie via l'API backup : les pages WAL et la révision appartiennent au même instant."""
    progress("Copie cohérente de la base")
    last = time.monotonic()

    def report(status, remaining, total):
        """Informe sur les pages copiées sans écrire de progression dans SQLite."""
        nonlocal last
        if time.monotonic() - last > 2 or remaining == 0:
            progress("Copie cohérente de la base", total - remaining, total=total)
            last = time.monotonic()

    target = sqlite3.connect(path)
    try:
        db.backup(target, pages=1000, progress=report)
        baseline = revision(target)
        maxima = {
            table: target.execute(f"SELECT COALESCE(MAX(id),0) FROM {table}").fetchone()[0]
            for table in (CAMPAIGN, *STAGED, *PROJECTED)
        }
    finally:
        target.close()
    return baseline, maxima


@contextlib.contextmanager
def private_database(path):
    """Redirige l'ORM du worker seul vers la copie privée, puis restaure toujours la connexion."""
    if connection.in_atomic_block:
        raise RuntimeError("La préparation doit démarrer hors transaction applicative")
    original = connection.settings_dict
    connection.close()
    connection.settings_dict = {**original, "NAME": str(path), "OPTIONS": {"timeout": 30}}
    try:
        yield
    finally:
        connection.close()
        connection.settings_dict = original


def columns(db, table):
    """Limite les identifiants SQL aux colonnes des tables internes autorisées."""
    if table not in (CAMPAIGN, *STAGED, *PROJECTED):
        raise ValueError("Table non autorisée à la publication")
    return [row[1] for row in db.execute(f"PRAGMA main.table_info({table})")]


def insert_prepared(db, table, lower, upper, *, hidden=False):
    """Copie un ensemble par INSERT SELECT, sans recréer un objet ORM par ligne."""
    names = columns(db, table)
    quoted = ",".join(f'"{name}"' for name in names)
    values = ",".join(
        "0" if hidden and name in ("published", "is_current") else f'"{name}"' for name in names
    )
    db.execute(
        f"INSERT INTO main.{table} ({quoted}) SELECT {values} FROM prepared.{table} "
        "WHERE id>? AND id<=? ORDER BY id",
        (lower, upper),
    )


def merge_projection(db, table, boundary):
    """Insère les nouvelles identités et met à jour en SQL seulement les lignes modifiées."""
    maximum = db.execute(f"SELECT COALESCE(MAX(id),0) FROM prepared.{table}").fetchone()[0]
    insert_prepared(db, table, boundary, maximum)
    names = [name for name in columns(db, table) if name != "id"]
    target = ",".join(f'"{name}"' for name in names)
    source = ",".join(f's."{name}"' for name in names)
    different = " OR ".join(f'm."{name}" IS NOT s."{name}"' for name in names)
    db.execute(
        f"UPDATE main.{table} AS m SET ({target}) = "
        f"(SELECT {source} FROM prepared.{table} s WHERE s.id=m.id) "
        f"WHERE m.id<=? AND EXISTS (SELECT 1 FROM prepared.{table} s "
        f"WHERE s.id=m.id AND ({different}))",
        (boundary,),
    )


def stage_and_publish(db, maxima, expected, *, job, count, progress):
    """Charge les gros instantanés par lots cachés, puis bascule sources et campagne ensemble."""
    new_campaign_max = db.execute(
        f"SELECT COALESCE(MAX(id),0) FROM prepared.{CAMPAIGN}"
    ).fetchone()[0]
    with write_batch(db, progress, "Création de la campagne non publiée", expected=expected):
        insert_prepared(db, CAMPAIGN, maxima[CAMPAIGN], new_campaign_max, hidden=True)
        expected = revision(db)
    for table in STAGED:
        lower, completed = maxima[table], 0
        while True:
            ids = db.execute(
                f"SELECT id FROM prepared.{table} WHERE id>? ORDER BY id LIMIT ?", (lower, BATCH)
            ).fetchall()
            if not ids:
                break
            upper = ids[-1][0]
            with write_batch(
                db, progress, f"Écriture par lots : {LABELS[table]}", expected=expected
            ):
                insert_prepared(db, table, lower, upper)
                expected = revision(db)
            completed += len(ids)
            progress(f"Écriture par lots : {LABELS[table]}", completed)
            lower = upper
    progress("Publication atomique")
    with write_batch(db, progress, "Publication atomique", expected=expected):
        for table in PROJECTED:
            merge_projection(db, table, maxima[table])
        # La contrainte d'unicité de la campagne courante reste vraie à chaque instruction.
        db.execute(f"UPDATE {CAMPAIGN} SET is_current=0 WHERE is_current=1")
        merge_projection(db, CAMPAIGN, new_campaign_max)
        if job:
            db.execute(
                "UPDATE imports_app_matchingjob SET state=?,active=0,finished_at=?, "
                "groups_imported=?,error=? WHERE id=?",
                ("SUCCESS", timezone.now().isoformat(), count, "", job.pk.hex),
            )
    progress("Terminé", count)


def staged_import(path, *, job=None, directory, progress):
    """Prépare la copie SQLite puis publie atomiquement, sans maintenance dans l'import.

    Le JSONL est validé et committé sur copie privée ; les statistiques puis le
    cadrage y sont préparés hors transaction englobante. Toute erreur empêche la
    publication et conserve la campagne active. Les synthèses sont transférées
    avec leurs contrôles, sans modifier leurs valeurs ni le protocole de publication.
    """
    from reconciliation.review_import import import_bundle

    from .models import MatchingJob

    database = Path(connection.settings_dict["NAME"]).resolve()
    private = directory / "preparation.sqlite3"
    if private.resolve() == database:
        raise ValueError("La préparation ne peut pas remplacer la base applicative")
    needed = 2 * database.stat().st_size + 3 * Path(path).stat().st_size
    if shutil.disk_usage(directory).free < needed:
        raise ValidationError(
            "Espace insuffisant pour préparer cet import sans toucher à la campagne courante"
        )
    db = open_database(database)
    try:
        revision(db)
        enable_wal(db)
        clear_unpublished(db, progress)
        # Le worker_lock protège ce répertoire contre deux préparations simultanées.
        for suffix in ("", "-wal", "-shm"):
            file = Path(str(private) + suffix)
            if file.exists():
                file.unlink()
        expected, maxima = make_snapshot(db, private, progress)
        if job:
            expected_hash = job.file_hash
        else:
            with Path(path).open("rb") as source:
                expected_hash = hashlib.file_digest(source, "sha256").hexdigest()
        with private_database(private):
            progress("Préparation et contrôles hors base métier")
            private_job = MatchingJob.objects.get(pk=job.pk) if job else None
            from reconciliation.sqlite_statistics import defer_private_accounting, maintain_statistics
            from reconciliation.accounting import prepare_campaign
            from reconciliation.models import Campaign
            with defer_private_accounting():
                count = import_bundle(path, job=private_job, progress=progress)
            campaign = Campaign.objects.filter(is_current=True, pk__gt=maxima[CAMPAIGN]).first()
            if campaign is not None:
                maintenance = maintain_statistics(after_import=True)
                progress("Statistiques SQLite : " + maintenance["status"], seconds=round(maintenance["seconds"], 3))
                if maintenance["status"] in ("failed", "deferred"):
                    raise ValidationError("Maintenance SQLite indisponible sur copie : publication annulée")
                prepare_campaign(campaign, progress=progress)
        with Path(path).open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected_hash:
                raise ValidationError("Le fichier a changé pendant la préparation")
        db.execute("ATTACH DATABASE ? AS prepared", (str(private),))
        try:
            stage_and_publish(db, maxima, expected, job=job, count=count, progress=progress)
        finally:
            db.execute("DETACH DATABASE prepared")
        # Publication déjà committée : un échec de maintenance reste un avertissement,
        # jamais une annulation fictive d'un import réussi. Aucune préparation ici.
        if campaign is not None:
            maintenance = maintain_statistics(after_import=True)
            progress("Statistiques SQLite publiées : " + maintenance["status"], seconds=round(maintenance["seconds"], 3))
        return count
    finally:
        db.close()
        # Les lots invisibles sont conservés en cas d'échec pour être nettoyés
        # au prochain lancement. Aucun nettoyage massif ne masque l'erreur initiale.
