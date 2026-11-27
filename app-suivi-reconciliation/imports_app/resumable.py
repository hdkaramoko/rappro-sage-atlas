"""Staging PostgreSQL isolé, checkpoints courts et publication métier atomique.

Les projections mutables restent exclusivement dans la transaction de publication.
Cette phase est encore monolithique ; les inventaires déjà commités sont réutilisés.
"""

import hashlib
import json
import time
from contextlib import contextmanager

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from reconciliation_contract.ods_party import party_context

from reconciliation.models import Campaign, CampaignDepartment
from .models import ImportIdentity, MatchingJob

PROTOCOL = 1
PUBLICATION_PHASE = "Finalisation et publication atomiques"


class InterruptedImport(Exception):
    """Arrêt demandé ; le lot en cours est annulé."""


class IncompatibleImport(ValidationError):
    pass


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class PersistentSet:
    def __init__(self, job, section, readonly=False):
        self.job, self.section, self.readonly = job, section, readonly

    def __contains__(self, value):
        return ImportIdentity.objects.filter(job=self.job, section=self.section, key=identity(value)).exists()

    def add(self, value):
        if self.readonly:
            return
        ImportIdentity.objects.create(job=self.job, section=self.section, key=identity(value))

    def __len__(self):
        return ImportIdentity.objects.filter(job=self.job, section=self.section).count()


def assert_owner(job, stop=None):
    """La session ayant acquis le verrou ne doit jamais être remplacée en silence."""
    from .jobs import assert_worker_session
    assert_worker_session()
    if stop is not None and stop.is_set():
        raise InterruptedImport("Arrêt demandé ; reprise au dernier checkpoint validé.")
    if not MatchingJob.objects.filter(pk=job.pk, generation=job.generation, active=True).exists():
        raise InterruptedImport("Le jeton du worker n'est plus valide.")


def verify_source(path, job, stop=None):
    """Relit le flux pour les deux SHA-256 ; aucun état hashlib n'est sérialisé.

    La relecture est intentionnelle, même après staging complet. Elle ne rejoue
    aucune écriture. Le parseur métier conserve les contrôles détaillés de contrat.
    """
    started = time.monotonic()
    raw_hash, normalized = hashlib.sha256(), hashlib.sha256()
    header, ending, size = None, None, 0
    with path.open("rb") as source:
        for number, raw in enumerate(source, 1):
            if stop is not None and stop.is_set():
                raise InterruptedImport("Arrêt pendant la vérification de la source.")
            raw_hash.update(raw)
            size += len(raw)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValidationError(f"Objet JSON attendu à la ligne {number}.")
            if ending is not None:
                raise ValidationError("Données après la fin du fichier")
            if header is None:
                header = payload
            if "complete" in payload:
                ending = payload
            else:
                normalized.update((json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n").encode())
    if header is None or ending is None:
        raise ValidationError("Fichier vide ou marqueur de fin absent")
    if job.file_hash and raw_hash.hexdigest() != job.file_hash:
        raise ValidationError("Le fichier a changé depuis son transfert. Import annulé.")
    if job.source_size and size != job.source_size:
        raise ValidationError("La taille du fichier a changé depuis son transfert.")
    if header.get("capabilities") and ending.get("stream_sha256") != normalized.hexdigest():
        raise ValidationError("Empreinte du flux normalisé incohérente")
    return header, ending, size, raw_hash.hexdigest(), time.monotonic() - started


def create_staging(job, header):
    """Ne crée ni Project, ni groupe, ni ligne de revue visible."""
    from reconciliation_contract.departments import validate_departments
    from reconciliation_contract.bap_history import POLICY as BAP_POLICY
    from reconciliation.multiple_import import validate_header
    from reconciliation.sage_import import validate_capabilities

    if header.get("schema_version") not in (2, 3):
        raise ValidationError("Version de campagne non prise en charge")
    validate_capabilities(header)
    if header["schema_version"] == 3:
        validate_header(header)
    if header.get("bap_history_policy") not in (None, BAP_POLICY):
        raise ValidationError("Politique d'historique BAP non prise en charge")
    for field in ("name", "scope"):
        if not isinstance(header.get(field), str) or not header[field].strip() or len(header[field]) > 200:
            raise ValidationError("Nom et périmètre de campagne requis (200 caractères maximum)")
    year = header.get("year")
    if year is not None and (type(year) is not int or not 2000 <= year <= 2200):
        raise ValidationError("Année de campagne invalide")
    try:
        departments = validate_departments(header)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    active = Campaign.objects.filter(is_current=True).first()
    if active and active.scope != header["scope"]:
        raise ValidationError("Périmètre différent : extraction cumulative du même périmètre requise.")
    # L'archivage des anciennes lignes est réservé à la publication. En staging
    # on ne matérialise pas encore cette éventuelle campagne de compatibilité.
    previous = Campaign.objects.filter(scope=header["scope"], fiscal_year=year).first()
    if previous is None and active and not active.inventory_complete:
        previous = active
    campaign = Campaign.all_objects.create(
        name=header["name"].strip(), scope=header["scope"], fiscal_year=year,
        metadata=header, previous=previous, job=job, file_hash=job.file_hash,
        published=False,
    )
    CampaignDepartment.objects.bulk_create([
        CampaignDepartment(campaign=campaign, project_code=code, source=row["source"],
                           consolidated=row["consolidated"], pole=row.get("pole", "Hors DP"),
                           pole_source=row.get("pole_source", ""))
        for code, row in departments.items()
    ], batch_size=500)
    return campaign


@party_context()
def _stage_batch(campaign, job, rows, state):
    from reconciliation.campaigns import normalize_inventory, insert_inventory, inventory_key
    from reconciliation.sage_import import insert_sage_batch
    from reconciliation.bap_history import insert_batch
    from reconciliation_contract.bap_history import bap_key
    from reconciliation_contract.sage_inventory import CAPABILITY

    inventory, sage, bap, keys = [], [], [], []
    counts = state.setdefault("counts", {})
    phase = state.get("section", "inventory")
    order = {"inventory": 0, "bap_history": 1, "sage_inventory": 2, "proposal": 3, "control": 4, "complete": 5}
    metadata = campaign.metadata
    for number, payload, offset in rows:
        section = "complete" if "complete" in payload else payload.get("type")
        if section not in order or order[section] < order[phase] or phase == "complete":
            raise ValidationError("Ordre ou type d'enregistrement de campagne invalide")
        phase = section
        counts[section] = counts.get(section, 0) + 1
        if section == "inventory":
            data = normalize_inventory(payload.get("atlas"), extended=metadata["schema_version"] == 3,
                                       ods_label_policy=metadata.get("ods_label_policy"))
            if campaign.fiscal_year is not None and data["fiscal_year"] != campaign.fiscal_year:
                raise ValidationError("Inventaire hors de l'année de campagne")
            inventory.append(data)
            target = bap_key(data.get("display_bap", ""))
            if metadata.get("bap_history_policy") and target:
                # Ces couples sont un ensemble (contrairement aux identités uniques).
                ImportIdentity.objects.get_or_create(job=job, section="bap_targets",
                                                     key=identity((data["project_code"], target)))
        elif section == "bap_history":
            if not metadata.get("bap_history_policy") or metadata["schema_version"] != 3:
                raise ValidationError("Historique BAP sans capacité compatible")
            bap.append(payload.get("data"))
        elif section == "sage_inventory":
            if CAPABILITY not in metadata.get("capabilities", []):
                raise ValidationError("Inventaire Sage sans capacité")
            sage.append(payload.get("data"))
        elif section == "proposal":
            if payload.get("schema_version") != metadata["schema_version"]:
                raise ValidationError("Schéma de proposition incompatible")
            keys.append(ImportIdentity(job=job, section="groups", key=identity(payload.get("key"))))
            for raw in payload.get("atlas", []):
                data = normalize_inventory(raw, extended=metadata["schema_version"] == 3,
                                           ods_label_policy=metadata.get("ods_label_policy"))
                keys.append(ImportIdentity(job=job, section="lines", key=identity(inventory_key(data))))
        elif section == "control":
            if metadata["schema_version"] != 3:
                raise ValidationError("Contrôle sans schéma v3")
            keys.append(ImportIdentity(job=job, section="controls", key=identity(payload.get("data", {}).get("key"))))
        elif section == "complete":
            for field, key in (("complete", "proposal"), ("inventory_count", "inventory")):
                if payload.get(field) != counts.get(key, 0):
                    raise ValidationError("Compteurs de campagne incohérents")
            if metadata["schema_version"] == 3 and payload.get("control_count") != counts.get("control", 0):
                raise ValidationError("Compteur des contrôles incohérent")
            if metadata.get("bap_history_policy") and payload.get("bap_history_count") != counts.get("bap_history", 0):
                raise ValidationError("Compteur BAP incohérent")
            if CAPABILITY in metadata.get("capabilities", []) and payload.get("sage_inventory_count") != counts.get("sage_inventory", 0):
                raise ValidationError("Compteur Sage incohérent")
    if inventory:
        insert_inventory(campaign, inventory)
    if sage:
        insert_sage_batch(campaign, sage)
    if bap:
        insert_batch(campaign, bap, PersistentSet(job, "bap_targets", readonly=True))
    try:
        with transaction.atomic():
            ImportIdentity.objects.bulk_create(keys, batch_size=500)
    except IntegrityError as exc:
        raise ValidationError("Identité répétée dans les propositions ou contrôles") from exc
    state["section"] = phase


@contextmanager
def publication_lock():
    """Gèle uniquement les écritures métier pendant la finalisation.

    SHARE ROW EXCLUSIVE laisse les SELECT ordinaires lire l'ancienne version.
    Acquérir tous les verrous avant de relire les décisions protège aussi les
    corrections historiques qui ne verrouillent pas la ligne Campaign.
    """
    if connection.vendor != "postgresql":
        yield
        return
    tables = sorted({model._meta.db_table for model in apps.get_models()
                     if model._meta.app_label in {"reconciliation", "projects"}})
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute("LOCK TABLE " + ", ".join(connection.ops.quote_name(t) for t in tables)
                       + " IN SHARE ROW EXCLUSIVE MODE")
    yield


def staged_postgres_import(path, job, header, progress, stop=None):
    from reconciliation.campaigns import import_campaign

    if job.protocol_version not in (0, PROTOCOL):
        raise IncompatibleImport("Version du protocole incompatible ; déployer une version compatible.")
    campaign = Campaign.all_objects.filter(job=job).first()
    if campaign is None:
        with transaction.atomic():
            assert_owner(job, stop)
            campaign = create_staging(job, header)
            with path.open("rb") as source:
                source.readline()
                job.next_offset = source.tell()
            job.protocol_version, job.line_number = PROTOCOL, 1
            job.checkpoint = {**job.checkpoint, "counts": {}, "section": "inventory"}
            job.save(update_fields=["protocol_version", "next_offset", "line_number", "checkpoint"])
    elif campaign.published:
        raise IncompatibleImport("Campagne déjà publiée : ne pas rejouer la publication.")
    if campaign.metadata != header:
        raise IncompatibleImport("En-tête différent du staging enregistré.")
    batch_size = max(1, settings.MATCHING_IMPORT_BATCH_SIZE)
    if job.checkpoint.get("section") != "complete":
        with path.open("rb") as source:
            source.seek(job.next_offset)
            while True:
                rows = []
                for index in range(batch_size):
                    raw = source.readline()
                    if not raw:
                        break
                    rows.append((job.line_number + index + 1, json.loads(raw.decode("utf-8")), source.tell()))
                if not rows:
                    break
                # JSON copy : un rollback ne doit pas laisser les compteurs Python
                # avancer au-delà de l'état commité.
                state = json.loads(json.dumps(job.checkpoint))
                with transaction.atomic():
                    assert_owner(job, stop)
                    _stage_batch(campaign, job, rows, state)
                    assert_owner(job, stop)
                    job.checkpoint = state
                    job.next_offset, job.line_number = rows[-1][2], rows[-1][0]
                    job.committed_batches += 1
                    job.phase = "Préparation : " + state["section"]
                    job.save(update_fields=["checkpoint", "next_offset", "line_number", "committed_batches", "phase"])
                progress(job.phase, sum(state["counts"].values()), durable=True)
    if job.checkpoint.get("section") != "complete":
        raise ValidationError("Campagne interrompue : marqueur de fin absent")
    assert_owner(job, stop)
    job.phase = PUBLICATION_PHASE
    job.save(update_fields=["phase"])
    progress(job.phase)
    started = time.monotonic()
    with transaction.atomic(), publication_lock():
        assert_owner(job, stop)
        with path.open(encoding="utf-8") as source:
            source.readline()
            count = import_campaign(header, source, job=job, progress=progress, prepared=campaign)
        assert_owner(job, stop)
        job.groups_imported, job.state, job.active = count, "SUCCESS", False
        job.finished_at, job.phase = timezone.now(), "Publication terminée"
        job.checkpoint = {**job.checkpoint, "publication_seconds": round(time.monotonic() - started, 3)}
        job.save(update_fields=["groups_imported", "state", "active", "finished_at", "phase", "checkpoint"])
    progress("Publication terminée", count)
