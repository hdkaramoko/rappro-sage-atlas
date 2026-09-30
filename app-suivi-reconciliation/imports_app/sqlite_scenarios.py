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
    """Utilise une base migrée neuve pour chaque scénario, indépendante du serveur."""

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
        """Une vraie écriture concurrente invalide la copie sans perdre la décision."""
        import_bundle(self.path)
        first = Campaign.objects.get(is_current=True).pk
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
        """Une panne en pleine publication laisse la photographie courante intacte."""
        from . import sqlite_staging

        import_bundle(self.path)
        first = Campaign.objects.get(is_current=True).pk
        self.path = self.bundle(2)
        original = sqlite_staging.merge_projection

        def fail(db, table, boundary):
            original(db, table, boundary)
            if table == "reconciliation_linereview":
                raise RuntimeError("panne simulée")

        with patch.object(sqlite_staging, "merge_projection", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.load()
        self.assertEqual(Campaign.objects.get(is_current=True).pk, first)
        self.assertEqual(LineReview.objects.count(), 1)
        self.load()
        self.assertEqual(LineReview.objects.count(), 2)
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
        """La publication SQL reproduit aussi les contributions et l'archive du parcours v1."""
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


if __name__ == "__main__":
    unittest.main(defaultTest="Scenarios", verbosity=2)
