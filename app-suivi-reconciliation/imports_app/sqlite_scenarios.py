"""Scénarios isolés sur disque ; lancer via test_sqlite_staging, jamais sur la base métier."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(sys.argv.pop(1)).resolve()
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

import django  # noqa: E402
from django.conf import settings  # noqa: E402

settings.DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ROOT / "initial.sqlite3"}
}
settings.MATCHING_JOB_ROOT = ROOT / "jobs"
django.setup()

from django.core.exceptions import ValidationError  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import override_settings  # noqa: E402

from accounts.models import User  # noqa: E402
from projects.models import Project, ProjectPortfolio  # noqa: E402
from reconciliation.models import Campaign, LineReview  # noqa: E402
from reconciliation.review_import import import_bundle  # noqa: E402
from reconciliation.test_campaigns import CampaignTests, atlas, proposal  # noqa: E402

from .jobs import job_directory, run_job  # noqa: E402
from .models import MatchingJob  # noqa: E402
from .sqlite_staging import staged_import  # noqa: E402


class Scenarios(unittest.TestCase):
    """Utilise une base neuve et vérifie publication, reprises et actions Lot 2 concurrentes.

    Les fichiers/bases sont isolés du serveur ; les scénarios exercent les vraies
    connexions SQLite, les liens manuels et les triggers de révision.
    """

    def setUp(self):
        """Isole fichiers et connexions, y compris les triggers de révision."""
        connection.close()
        self.folder = ROOT / self._testMethodName
        self.folder.mkdir()
        self.database = self.folder / "live.sqlite3"
        connection.settings_dict["NAME"] = str(self.database)
        call_command("migrate", verbosity=0)
        self.user = User.objects.create_user("reviewer")
        self.path = self.bundle()

    def tearDown(self):
        """Libère les fichiers avant suppression du répertoire temporaire parent."""
        connection.close()

    def bundle(self, count=1, complete=True):
        """Produit une campagne v2 valide comportant autant de groupes que demandé."""
        rows = [atlas(str(i)) for i in range(count)]
        records = [{"type": "campaign", "schema_version": 2, "scope": "test", "name": "Test"}]
        records += [{"type": "inventory", "atlas": row} for row in rows]
        records += [proposal([row], key=f"g{i}") for i, row in enumerate(rows)]
        if complete:
            records.append({"complete": count, "inventory_count": count})
        path = self.folder / "input.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        return path

    def load(self, progress=None):
        """Prépare et publie via le véritable circuit SQLite."""
        return staged_import(
            self.path, directory=self.folder, progress=progress or (lambda *a, **k: None)
        )

    def test_inventory_only_projects_survive_publication(self):
        """Transfère tous les projets Atlas de la copie privée sans créer de portefeuille."""
        records = [json.loads(row) for row in self.path.read_text(encoding="utf-8").splitlines()]
        extra = [atlas(code, **{"Code projet": code, "Statut BAP": "Comptabilisé"})
                 for code in ("Q", "R")]
        records[2:2] = [{"type": "inventory", "atlas": row} for row in extra]
        records[-1]["inventory_count"] = 3
        self.path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        self.assertEqual(self.load(), 1)
        self.assertSetEqual(set(Project.objects.values_list("code", flat=True)), {"P", "Q", "R"})
        current = Campaign.objects.get(is_current=True)
        self.assertEqual(current.inventory.count(), 3)
        self.assertEqual(current.accounting_projects.count(), 3)
        self.assertEqual(current.reviews.count(), 1)
        self.assertFalse(ProjectPortfolio.objects.exists())
        # Un nouvel import conserve les identités et les métadonnées déjà publiées.
        Project.objects.filter(code="Q").update(is_active=False, label="Conservé")
        records[0]["name"] = "Deuxième campagne"
        self.path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        self.assertEqual(self.load(), 1)
        self.assertEqual(Project.objects.count(), 3)
        self.assertFalse(Project.objects.get(code="Q").is_active)
        self.assertEqual(Project.objects.get(code="Q").label, "Conservé")

    def test_department_snapshot_survives_staging_and_idempotence(self):
        """Vérifie département/pôle via la fixture de l'environnement moteur et le staging."""
        root = Path(__file__).resolve().parents[2]
        program = "from examples.ods_bap_filters_fixture import generate; import sys; generate(sys.argv[1], project_departments={'P': {'source':'Sante','consolidated':'SANTE','in_reference':True,'pole':'Agriculture','pole_source':' Agriculture '}},pole_configuration={'followed':['Agriculture'],'fallback':'Hors DP'})"
        subprocess.run([str(root / ".venv/Scripts/python.exe"), "-c", program, str(self.folder)], cwd=root,
                       check=True, capture_output=True, timeout=60)
        self.path = self.folder / "ods-bap.jsonl"
        self.assertEqual(self.load(), 1)
        current = Campaign.objects.get(is_current=True)
        self.assertEqual(current.departments.get(project_code="P").consolidated, "SANTE")
        self.assertEqual(current.departments.get(project_code="P").pole, "Agriculture")
        self.assertEqual(current.departments.get(project_code="P").pole_source, " Agriculture ")
        count = Campaign.objects.count()
        self.assertEqual(self.load(), 1)
        self.assertEqual(Campaign.objects.count(), count)
        self.assertEqual(current.departments.count(), 1)

    def test_batches_readers_and_validation_carry(self):
        """Plus de 500 lignes : lecteurs disponibles et validation conservée après bascule."""
        import_bundle(self.path)
        first = Campaign.objects.get(is_current=True)
        ProjectPortfolio.objects.create(user=self.user, project=Project.objects.get(code="P"))
        CampaignTests.validate(self)
        self.path = self.bundle(501)
        stages = []

        def observe(phase, completed=None, **details):
            if phase.startswith("Écriture par lots"):
                with sqlite3.connect(self.database, timeout=0.1) as reader:
                    self.assertEqual(
                        reader.execute(
                            "SELECT id FROM reconciliation_campaign WHERE is_current=1"
                        ).fetchone()[0],
                        first.pk,
                    )
                    self.assertEqual(
                        reader.execute(
                            "SELECT count(*) FROM reconciliation_campaign WHERE published=1"
                        ).fetchone()[0],
                        1,
                    )
                    stages.append(phase)

        self.assertEqual(self.load(observe), 501)
        self.assertGreaterEqual(len(stages), 4)
        current = Campaign.objects.get(is_current=True)
        self.assertNotEqual(current.pk, first.pk)
        self.assertEqual(current.reviews.get(source__source_id="0").comparison, "CARRIED")
        self.assertEqual(current.inventory.count(), 501)
        self.assertEqual(Campaign.objects.count(), 2)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_concurrent_decision_prevents_publication(self):
        """Un nouvel import réel détecte la concurrence ; un réimport identique est idempotent."""
        import_bundle(self.path)
        first = Campaign.objects.get(is_current=True).pk
        records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        records[0]["name"] = "Nouvelle campagne concurrente"
        self.path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        edited = False

        def edit(phase, *args, **details):
            nonlocal edited
            if phase.startswith("Écriture par lots") and not edited:
                with sqlite3.connect(self.database) as db:
                    db.execute("UPDATE reconciliation_linereview SET comment='decision recente'")
                edited = True

        with self.assertRaises(ValidationError):
            self.load(edit)
        self.assertTrue(edited)
        self.assertEqual(Campaign.objects.get(is_current=True).pk, first)
        self.assertEqual(LineReview.objects.get().comment, "decision recente")
        self.assertEqual(Campaign.objects.count(), 1)
        self.assertTrue(Campaign.all_objects.filter(published=False).exists())
        self.load()
        self.assertFalse(Campaign.all_objects.filter(published=False).exists())
        self.assertEqual(LineReview.objects.get().comment, "decision recente")

    def test_publication_failure_rolls_back_and_retry_cleans_staging(self):
        """Une panne de publication annule aussi les nouveaux projets ; la reprise les crée."""
        from . import sqlite_staging

        import_bundle(self.path)
        first = Campaign.objects.get(is_current=True).pk
        self.path = self.bundle(2)
        records = [json.loads(row) for row in self.path.read_text(encoding="utf-8").splitlines()]
        records.insert(1, {"type": "inventory", "atlas": atlas("Q", **{
            "Code projet": "Q", "Statut BAP": "Comptabilisé"})})
        records[-1]["inventory_count"] += 1
        self.path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        original = sqlite_staging.merge_projection

        def fail(db, table, boundary):
            """Simule une panne après transfert de Project, dans la transaction de publication."""
            original(db, table, boundary)
            if table == "reconciliation_linereview":
                raise RuntimeError("panne simulée")

        with patch.object(sqlite_staging, "merge_projection", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.load()
        self.assertEqual(Campaign.objects.get(is_current=True).pk, first)
        self.assertEqual(LineReview.objects.count(), 1)
        self.assertFalse(Project.objects.filter(code="Q").exists())
        self.load()
        self.assertEqual(LineReview.objects.count(), 2)
        self.assertTrue(Project.objects.filter(code="Q").exists())
        self.assertFalse(Campaign.all_objects.filter(published=False).exists())

    def test_truncated_file_does_not_change_live_database(self):
        """Le contrôle de fin de fichier précède toute mutation métier réelle."""
        import_bundle(self.path)
        self.path = self.bundle(2, complete=False)
        with self.assertRaises(ValidationError):
            self.load()
        self.assertEqual(Campaign.all_objects.count(), 1)
        self.assertEqual(LineReview.objects.count(), 1)

    def test_worker_success_and_duplicate(self):
        """Le worker publie son succès dans la même transaction que la campagne."""
        content = self.path.read_bytes()
        for expected in ("SUCCESS", "DUPLICATE"):
            job = MatchingJob.objects.create(
                created_by=self.user,
                bundle_name="input.jsonl",
                state="QUEUED",
                file_hash=hashlib.sha256(content).hexdigest(),
                active=True,
            )
            directory = job_directory(job)
            directory.mkdir(parents=True)
            (directory / "propositions.jsonl").write_bytes(content)
            run_job(job.pk)
            job.refresh_from_db()
            self.assertEqual(job.state, expected, job.error)
            self.assertFalse(job.active)
        self.assertEqual(Campaign.objects.count(), 1)

    def test_multiples_and_legacy_preserve_prepared_result(self):
        """La publication d'une nouvelle campagne reporte les contributions et archive le v1."""
        from reconciliation.test_multiples import MultipleTests

        from .sqlite_staging import CAMPAIGN, PROJECTED, STAGED

        # Une ligne historique validée doit être archivée lors de la première campagne.
        legacy = proposal([atlas("old")], schema_version=1)
        self.path.write_text(json.dumps(legacy) + '\n{"complete": 1}', encoding="utf-8")
        self.load()
        ProjectPortfolio.objects.create(user=self.user, project=Project.objects.get(code="P"))
        CampaignTests.validate(self)
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                str(root / ".venv/Scripts/python.exe"),
                "-m",
                "examples.multiples_fixture",
                str(self.folder / "fixture"),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.path = self.folder / "fixture/campaign.jsonl"
        self.load()
        MultipleTests.validate(self, "A")
        records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        records[0]["name"] = "Nouvelle photographie des multiples"
        self.path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        self.load()
        campaign = Campaign.objects.get(is_current=True)
        self.assertEqual(campaign.reviews.get(source__source_id="A").comparison, "CARRIED")
        with (
            sqlite3.connect(self.database) as live,
            sqlite3.connect(self.folder / "preparation.sqlite3") as prepared,
        ):
            for table in (CAMPAIGN, *STAGED, *PROJECTED):
                self.assertEqual(
                    live.execute(f"SELECT * FROM {table} ORDER BY id").fetchall(),
                    prepared.execute(f"SELECT * FROM {table} ORDER BY id").fetchall(),
                    table,
                )
            self.assertEqual(live.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_wal_reader_while_write_transaction_open(self):
        """Une seconde connexion lit encore les données pendant une écriture non validée."""
        from .sqlite_staging import enable_wal, open_database, write_batch

        import_bundle(self.path)
        writer = open_database(self.database)
        try:
            enable_wal(writer)
            with write_batch(writer, lambda *a, **k: None, "test"):
                writer.execute("UPDATE reconciliation_linereview SET comment='non publie'")
                with sqlite3.connect(self.database, timeout=0.1) as reader:
                    self.assertEqual(
                        reader.execute("SELECT comment FROM reconciliation_linereview").fetchone()[
                            0
                        ],
                        "",
                    )
        finally:
            writer.close()

    def test_lot1_inventory_and_controls_survive_staging(self):
        """Transporte photographies, états indexés et contextes dans la publication atomique."""
        root = Path(__file__).resolve().parents[2]
        folder = self.folder / "lot1"
        result = subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.lot1_fixture", str(folder)],
                                cwd=root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.path = folder / "campaign.jsonl"
        self.load()
        campaign = Campaign.objects.get(is_current=True)
        self.assertEqual(campaign.sage_inventory.count(), 4)
        self.assertFalse(campaign.global_controls.filter(current_state__isnull=True).exists())
        self.assertFalse(campaign.global_controls.filter(has_pending__isnull=True).exists())
        self.assertTrue(campaign.review_control_contexts.exists())
        self.assertEqual(campaign.global_controls.count(), 3)
        self.assertTrue(campaign.global_controls.get(data__identity__strategy="ODS_ODG_BY_GROUP").data["auto_validated"])

    def test_lot2_correction_prevents_publication_of_a_stale_import(self):
        """Une correction concurrente garde son audit et invalide la préparation SQLite.

        La relance reprend la correction sur les sources identiques. Exerce
        les vraies tables/triggers et la copie des actions sur base sur disque.
        """
        from reconciliation.business import correct_inventory, retained_amount
        from reconciliation.test_sage_inventory import sign_records
        root = Path(__file__).resolve().parents[2]
        folder = self.folder / "lot2"
        subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.lot1_fixture", str(folder)],
                       cwd=root, check=True, capture_output=True, timeout=60)
        self.path = folder / "campaign.jsonl"
        records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        for row in records:
            if row.get("type") == "proposal":
                row.pop("auto_validation", None)
        sign_records(records)
        self.path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        self.load()
        first = Campaign.objects.get(is_current=True)
        ProjectPortfolio.objects.create(user=self.user, project=Project.objects.get(code="P"))
        inventory = first.inventory.get(source_id="C")
        records[0]["name"] = "Nouvelle campagne pendant correction"
        sign_records(records)
        self.path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        changed = False

        def edit(phase, *args, **details):
            """Simule une vraie action métier après un lot caché, hors verrou SQLite."""
            nonlocal changed
            if phase.startswith("Écriture par lots") and not changed:
                correct_inventory(inventory.pk, self.user, reason="AMOUNT", amount="5000", expected_version=0)
                changed = True

        with self.assertRaises(ValidationError):
            self.load(edit)
        self.assertTrue(changed)
        self.assertEqual(Campaign.objects.get(is_current=True).pk, first.pk)
        inventory.refresh_from_db()
        self.assertEqual(retained_amount(inventory), 5000)
        self.assertEqual(inventory.business_events.count(), 1)
        self.load()
        current = Campaign.objects.get(is_current=True)
        self.assertNotEqual(current.pk, first.pk)
        self.assertEqual(current.inventory.get(source_id="C").adjustment.amount, 5000)
        from reconciliation.business import confirm_inventory_link
        source = current.inventory.get(source_id="S")
        entry = current.sage_inventory.get(document="FAC123", amount="4000")
        confirm_inventory_link(source.pk, self.user, entry_ids=[entry.pk], comment="Lien avant nouvel import", expected_version=0)
        records[0]["name"] = "Campagne après lien manuel local"
        sign_records(records)
        self.path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        self.load()
        latest = Campaign.objects.get(is_current=True)
        self.assertTrue(latest.inventory.get(source_id="S").inventory_match.active)
        self.assertTrue(latest.reviews.get(source__source_id="S").decision["current"])
        self.assertTrue(current.inventory.get(source_id="S").inventory_match.active)

    def test_activation_backs_up_and_refuses_running_worker(self):
        """L'installation préserve les campagnes et ne migre jamais sous un worker actif."""
        from .jobs import worker_lock

        import_bundle(self.path)
        call_command("migrate", "reconciliation", "0010_multiple_controls_assignments", verbosity=0)
        with override_settings(BASE_DIR=self.folder):
            with worker_lock(), self.assertRaises(CommandError):
                call_command("prepare_sqlite_imports", migrate=True, stdout=StringIO())
            self.assertFalse((self.folder / "var/backups").exists())
            call_command("prepare_sqlite_imports", migrate=True, stdout=StringIO())
            backups = list((self.folder / "var/backups").glob("*.sqlite3"))
            self.assertEqual(len(backups), 1)
            with sqlite3.connect(backups[0]) as backup:
                self.assertEqual(
                    backup.execute("SELECT count(*) FROM reconciliation_campaign").fetchone()[0], 1
                )
        self.assertEqual(Campaign.objects.get().published, True)
        call_command("makemigrations", check=True, dry_run=True, stdout=StringIO())


    def test_statistics_are_outside_import_and_before_private_preparation(self):
        """Le staging analyse la copie après commit, prépare puis publie ses synthèses atomiquement."""
        from reconciliation.accounting import prepare_campaign
        from reconciliation.sqlite_statistics import maintain_statistics
        from reconciliation.accounting_models import AccountingProject
        events = []

        def observe_statistics(**kwargs):
            """Relève la séquence et le contexte transactionnel sans changer la maintenance réelle."""
            self.assertFalse(connection.in_atomic_block)
            events.append("statistics")
            return maintain_statistics(**kwargs)

        def observe_preparation(campaign, **kwargs):
            """Vérifie le commit privé avant d'appeler le vrai calcul, sans modifier ses valeurs."""
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(events, ["statistics"])
            events.append("preparation")
            return prepare_campaign(campaign, **kwargs)

        with patch("reconciliation.sqlite_statistics.maintain_statistics", side_effect=observe_statistics), patch(
                "reconciliation.accounting.prepare_campaign", side_effect=observe_preparation):
            self.load()
        self.assertEqual(events, ["statistics", "preparation", "statistics"])
        self.assertEqual(AccountingProject.objects.filter(campaign__is_current=True).count(), 1)

    def test_statistics_failure_keeps_current_campaign_unmodified(self):
        """Un échec sur la copie empêche toute publication et laisse les données existantes intactes."""
        import_bundle(self.path)
        previous = Campaign.objects.get(is_current=True)
        records = [json.loads(row) for row in self.path.read_text(encoding="utf-8").splitlines()]
        records[0]["name"] = "Nouveau fichier de recette"
        self.path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        with patch("reconciliation.sqlite_statistics.maintain_statistics", return_value={
                "status": "failed", "seconds": 0}):
            with self.assertRaises(ValidationError):
                self.load()
        self.assertEqual(Campaign.objects.get(is_current=True).pk, previous.pk)
        self.assertEqual(Campaign.objects.count(), 1)


if __name__ == "__main__":
    unittest.main(defaultTest="Scenarios", verbosity=2)
