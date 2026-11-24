"""Transactions réelles : rollback du lot, reprise et publication isolée.

Exécutés sur SQLite pour le parseur, et sur PostgreSQL en CI pour les verrous,
sessions, commits et concurrence. Aucun commit métier n'est mocké.
"""

import hashlib
import json
import subprocess
import sys
import threading
import uuid
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from reconciliation.models import Campaign, CampaignGroup, LineReview, ReviewGroup
from reconciliation.review_import import import_bundle
from reconciliation.test_campaigns import atlas, proposal
from .jobs import run_job, worker_lock
from .models import MatchingJob
from .resumable import staged_postgres_import, verify_source, _stage_batch


class KilledWorker(BaseException):
    pass


class ResumableImportTests(TransactionTestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        override = override_settings(MATCHING_JOB_ROOT=self.root, MATCHING_IMPORT_BATCH_SIZE=2)
        override.enable()
        self.addCleanup(override.disable)

    def records(self, count=5):
        rows = [atlas(str(i)) for i in range(count)]
        return [{"type": "campaign", "schema_version": 2, "scope": "test", "name": "Test"},
                *[{"type": "inventory", "atlas": row} for row in rows],
                *[proposal([row], key=f"g{i}") for i, row in enumerate(rows)],
                {"complete": count, "inventory_count": count}]

    def job(self, records=None):
        job = MatchingJob.objects.create(bundle_name="test.jsonl", state="QUEUED", generation=uuid.uuid4())
        directory = self.root / str(job.pk)
        directory.mkdir()
        path = directory / "propositions.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (records or self.records())) + "\n", encoding="utf-8")
        job.file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        job.source_size = path.stat().st_size
        job.save()
        return job, path

    def execute(self, job, path, progress=lambda *args, **kwargs: None):
        with worker_lock():
            header, *_ = verify_source(path, job)
            staged_postgres_import(path, job, header, progress)

    def test_committed_batch_survives_and_rollback_does_not_advance_checkpoint(self):
        job, path = self.job()
        def crash(*args, **kwargs):
            raise KilledWorker()
        with self.assertRaises(KilledWorker):
            self.execute(job, path, crash)
        job.refresh_from_db()
        stage = Campaign.all_objects.get(job=job)
        self.assertEqual(stage.inventory.count(), 2)
        self.assertEqual(job.line_number, 3)
        self.assertFalse(Campaign.objects.exists())
        self.assertFalse(ReviewGroup.objects.exists())
        checkpoint = job.next_offset
        def before_commit(*args, **kwargs):
            _stage_batch(*args, **kwargs)
            raise KilledWorker()
        with patch("imports_app.resumable._stage_batch", before_commit), self.assertRaises(KilledWorker):
            self.execute(job, path)
        job.refresh_from_db()
        self.assertEqual(job.next_offset, checkpoint)
        self.assertEqual(stage.inventory.count(), 2)
        self.execute(job, path)
        job.refresh_from_db()
        self.assertEqual(job.state, "SUCCESS")
        self.assertEqual(Campaign.objects.get().pk, stage.pk)
        self.assertEqual(stage.inventory.count(), 5)
        self.assertEqual(LineReview.objects.count(), 5)

    def test_publication_failure_preserves_staging_and_previous_live_projection(self):
        records = self.records()
        old_path = self.root / "old.jsonl"
        old_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        import_bundle(old_path)
        previous = Campaign.objects.get(is_current=True)
        before = list(ReviewGroup.objects.order_by("pk").values("key", "version", "context_signature"))
        records[0]["name"] = "Suivant"
        job, path = self.job(records)
        with patch("reconciliation.accounting.prepare_campaign", side_effect=RuntimeError("publication")), self.assertRaisesRegex(RuntimeError, "publication"):
            self.execute(job, path)
        job.refresh_from_db()
        stage = Campaign.all_objects.get(job=job)
        self.assertFalse(stage.published)
        self.assertEqual(job.checkpoint["section"], "complete")
        self.assertEqual(Campaign.objects.get(is_current=True).pk, previous.pk)
        self.assertEqual(before, list(ReviewGroup.objects.order_by("pk").values("key", "version", "context_signature")))
        with patch("reconciliation.campaigns.insert_inventory", side_effect=AssertionError("inventaire rejoué")):
            self.execute(job, path)
        self.assertEqual(Campaign.objects.get(is_current=True).pk, stage.pk)
        with self.assertRaises(ValidationError):
            self.execute(job, path)

    def test_duplicates_across_batches_are_rejected_without_live_writes(self):
        records = self.records()
        records[-2]["key"] = records[6]["key"]
        job, path = self.job(records)
        with self.assertRaises(ValidationError):
            self.execute(job, path)
        self.assertFalse(Campaign.objects.exists())
        self.assertFalse(LineReview.objects.exists())

    def test_source_integrity_and_end_marker(self):
        job, path = self.job()
        original = path.read_bytes()
        for content in (original[:-30], original + b'{}\n', original.replace(b'Test', b'Autr')):
            path.write_bytes(content)
            with self.assertRaises((ValidationError, ValueError)):
                verify_source(path, job)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            verify_source(path, job)

    def test_decision_made_during_staging_is_carried_from_latest_state(self):
        from accounts.models import User
        from projects.models import Project, ProjectPortfolio
        from reconciliation.review import decide, signature, is_current
        records = self.records(1)
        old_path = self.root / "old.jsonl"
        old_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        import_bundle(old_path)
        user = User.objects.create_user("reviewer")
        ProjectPortfolio.objects.create(user=user, project=Project.objects.get(code="P"))
        records[0]["name"] = "Suivant"
        job, path = self.job(records)
        with self.assertRaises(KilledWorker):
            self.execute(job, path, lambda *args, **kwargs: (_ for _ in ()).throw(KilledWorker()))
        line = LineReview.objects.select_related("transaction", "group").get()
        decide(line.pk, user, state="VALIDATED", comment="Décision pendant le staging",
               values={key: {"mode": "SET", "value": value} for key, value in {
                   "amount": "100", "status": "Comptabilisé", "document": "D", "date": "2026-01-01"}.items()},
               expected_version=line.version, expected_group_version=line.group.version,
               expected_source=signature(line), acknowledge=True)
        job.refresh_from_db()
        self.execute(job, path)
        line.refresh_from_db()
        self.assertEqual(line.comment, "Décision pendant le staging")
        self.assertTrue(is_current(line))
        self.assertEqual(Campaign.objects.get(is_current=True).reviews.get().comparison, "CARRIED")

    def test_baseline_and_resumed_import_have_same_business_result(self):
        job, path = self.job()
        records = self.records()
        import_bundle(path)
        baseline = self.snapshot()
        call_command("flush", verbosity=0, interactive=False)
        job, path = self.job(records)
        with self.assertRaises(KilledWorker):
            self.execute(job, path, lambda *args, **kwargs: (_ for _ in ()).throw(KilledWorker()))
        job.refresh_from_db()
        self.execute(job, path)
        self.assertEqual(self.snapshot(), baseline)

    def snapshot(self):
        campaign = Campaign.objects.get(is_current=True)
        line_keys = {str(line.pk): line.transaction.business_key for line in LineReview.objects.select_related("transaction")}
        def stable(value):
            if isinstance(value, list):
                return [stable(item) for item in value]
            if isinstance(value, dict):
                return {key: line_keys.get(str(item), item) if key == "line_key" else stable(item)
                        for key, item in value.items()}
            return value
        from reconciliation_contract import digest
        global_rows = list(campaign.global_controls.order_by("key").values("key", "data"))
        for row in global_rows:
            data = row["data"]
            self.assertEqual(data["signature"], digest({k: v for k, v in data.items() if k != "signature"}))
            row["data"] = stable(data)
            row["data"]["signature"] = digest({k: v for k, v in row["data"].items() if k != "signature"})
        return {"inventory": list(campaign.inventory.order_by("business_key").values("business_key", "data", "change")),
                "groups": list(CampaignGroup.objects.filter(campaign=campaign).order_by("key").values("key", "data")),
                "controls": list(campaign.controls.order_by("key").values("key", "status", "data")),
                "sage": list(campaign.sage_inventory.order_by("record_id").values("record_id", "data")),
                "global": global_rows,
                "reviews": [(r.source["source_id"], r.fingerprint, r.comparison, r.decision["state"], r.decision["values"])
                            for r in campaign.reviews.order_by("source__source_id")]}

    def test_missing_ods_party_policy_matches_atomic_import(self):
        root = Path(__file__).resolve().parents[2]
        executable = root / ".venv" / "Scripts" / "python.exe"
        fixture = self.root / "ods"
        fixture.mkdir()
        result = subprocess.run([str(executable) if executable.exists() else sys.executable,
                                 "-m", "examples.ods_bap_filters_fixture", str(fixture)],
                                cwd=root, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        records = [json.loads(line) for line in (fixture / "ods-bap.jsonl").read_text(encoding="utf-8").splitlines()]
        job, path = self.job(records)
        import_bundle(path)
        baseline = self.snapshot()
        call_command("flush", verbosity=0, interactive=False)
        job, path = self.job(records)
        with self.assertRaises(KilledWorker):
            self.execute(job, path, lambda *args, **kwargs: (_ for _ in ()).throw(KilledWorker()))
        job.refresh_from_db()
        self.execute(job, path)
        self.assertEqual(self.snapshot(), baseline)

    def test_v3_optional_sources_and_controls_survive_resume(self):
        root = Path(__file__).resolve().parents[2]
        executable = root / ".venv" / "Scripts" / "python.exe"
        result = subprocess.run([str(executable) if executable.exists() else sys.executable,
                                 "-m", "examples.lot1_fixture", str(self.root / "fixture")],
                                cwd=root, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        records = [json.loads(line) for line in (self.root / "fixture" / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
        records[0]["bap_history_policy"] = "bap-history-v1"
        next(r for r in records if r.get("type") == "inventory")["atlas"]["N° BAP (SAGE)"] = "BAP-TEST"
        position = next(i for i, r in enumerate(records) if r.get("type") == "sage_inventory")
        records.insert(position, {"type": "bap_history", "data": {
            "project_code": "P", "bap_sage_number": "BAP-TEST", "bap_created_at": "2026-01-02T15:30:00",
            "bap_created_by": "Auteur", "bap_modified_at": None, "bap_modified_by": None}})
        records[-1]["bap_history_count"] = 1
        records[-1]["stream_sha256"] = hashlib.sha256("".join(
            json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records[:-1]).encode()).hexdigest()
        job, path = self.job(records)
        with self.assertRaises(KilledWorker):
            self.execute(job, path, lambda *args, **kwargs: (_ for _ in ()).throw(KilledWorker()))
        job.refresh_from_db()
        self.execute(job, path)
        campaign = Campaign.objects.get(is_current=True)
        self.assertEqual(campaign.sage_inventory.count(), 4)
        self.assertEqual(campaign.bap_history.get().bap_created_by, "Auteur")
        self.assertTrue(campaign.controls.exists())
        self.assertTrue(campaign.global_controls.exists())


@skipUnless(connection.vendor == "postgresql", "PostgreSQL réel requis")
class PostgreSQLRunnerTests(ResumableImportTests):
    def test_failed_finalization_remains_manually_resumable(self):
        job, path = self.job()
        with patch("reconciliation.accounting.prepare_campaign", side_effect=RuntimeError("Publication indisponible")):
            run_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, "RETRYABLE")
        self.assertFalse(job.active)
        stage = Campaign.all_objects.get(job=job)
        self.assertFalse(stage.published)
        run_job(job.pk, resume=True)
        job.refresh_from_db()
        self.assertEqual(job.state, "SUCCESS", job.error)
        self.assertEqual(Campaign.objects.get(is_current=True).pk, stage.pk)

    def test_missing_source_waits_for_manual_recovery(self):
        job, path = self.job()
        original = path.read_bytes()
        path.unlink()
        run_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, "RETRYABLE")
        self.assertFalse(job.active)
        self.assertIsNone(run_job())
        path.write_bytes(original)
        run_job(job.pk, resume=True)
        job.refresh_from_db()
        self.assertEqual(job.state, "SUCCESS", job.error)

    def test_transient_failure_has_backoff(self):
        from django.utils import timezone
        job, path = self.job()
        with patch("imports_app.resumable._stage_batch", side_effect=OSError("Disque temporairement indisponible")):
            run_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, "RETRYABLE")
        self.assertTrue(job.active)
        self.assertGreater(job.next_attempt_at, timezone.now())
        self.assertIsNone(run_job())
        run_job(job.pk, resume=True)
        job.refresh_from_db()
        self.assertEqual(job.state, "SUCCESS", job.error)

    def test_process_killed_before_and_after_commit_resumes_without_duplicates(self):
        """Tue un vrai processus, sans simuler le rollback ou la connexion PostgreSQL."""
        child_code = '''
import os
import threading
from pathlib import Path
import django
django.setup()
from imports_app.jobs import run_job
from imports_app.progress import ImportProgress
from imports_app import resumable
marker = Path(os.environ['IMPORT_CRASH_MARKER'])
def pause():
    marker.write_text('ready')
    threading.Event().wait(60)
if os.environ['IMPORT_CRASH_WHEN'] == 'before':
    original = resumable._stage_batch
    def batch(*args, **kwargs):
        original(*args, **kwargs)
        pause()
    resumable._stage_batch = batch
else:
    original = ImportProgress.__call__
    def progress(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if kwargs.get('durable'):
            pause()
    ImportProgress.__call__ = progress
run_job(os.environ['IMPORT_JOB_ID'])
'''
        for when in ("before", "after"):
            with self.subTest(when=when):
                records = self.records()
                records[0]["name"] = when
                job, path = self.job(records)
                marker = self.root / f"{when}.ready"
                env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.import_test_settings",
                       "IMPORT_TEST_POSTGRES": "1", "IMPORT_TEST_DB": connection.settings_dict["NAME"],
                       "IMPORT_TEST_HOST": connection.settings_dict["HOST"],
                       "IMPORT_TEST_PORT": str(connection.settings_dict["PORT"]),
                       "IMPORT_TEST_USER": connection.settings_dict["USER"],
                       "IMPORT_TEST_PASSWORD": connection.settings_dict["PASSWORD"],
                       "MATCHING_JOB_ROOT": str(self.root), "MATCHING_IMPORT_BATCH_SIZE": "2",
                       "IMPORT_JOB_ID": str(job.pk), "IMPORT_CRASH_MARKER": str(marker), "IMPORT_CRASH_WHEN": when}
                process = subprocess.Popen([sys.executable, "-c", child_code],
                    cwd=Path(__file__).resolve().parents[1], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 20
                    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.1)
                    self.assertTrue(marker.exists(), "Le worker n'a pas atteint le point d'interruption")
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=10)
                job.refresh_from_db()
                stage = Campaign.all_objects.get(job=job)
                self.assertEqual(stage.inventory.count(), 0 if when == "before" else 2)
                run_job(job.pk, resume=True)
                job.refresh_from_db()
                self.assertEqual(job.state, "SUCCESS", job.error)
                self.assertEqual(stage.inventory.count(), 5)
                self.assertEqual(Campaign.objects.get(is_current=True).pk, stage.pk)

    def test_lost_worker_session_cannot_write_again(self):
        from .jobs import assert_worker_session
        with worker_lock():
            connection.close()
            with self.assertRaisesRegex(RuntimeError, "Session du verrou perdue"):
                assert_worker_session()

    def test_zombie_does_not_overwrite_new_worker_generation_on_failure(self):
        job, path = self.job()
        replacement = uuid.uuid4()
        def lost_session(*args, **kwargs):
            connection.close()
            other = connection.copy()
            try:
                with other.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(%s)", [734129826])
                    self.assertTrue(cursor.fetchone()[0])
                    cursor.execute('UPDATE imports_app_matchingjob SET generation=%s, error=%s WHERE id=%s',
                                   [replacement, "Nouveau worker", job.pk])
            finally:
                other.close()
            raise RuntimeError("Ancien worker")
        with patch("imports_app.resumable.staged_postgres_import", lost_session), self.assertRaisesRegex(RuntimeError, "Session du verrou perdue"):
            run_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.generation, replacement)
        self.assertEqual(job.error, "Nouveau worker")
        self.assertEqual(job.state, "IMPORTING")

    def test_worker_recovers_active_job_with_same_uuid(self):
        job, path = self.job()
        with patch("imports_app.resumable._stage_batch", side_effect=KilledWorker()), self.assertRaises(KilledWorker):
            run_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, "IMPORTING")
        self.assertEqual(run_job(resume=True), job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, "SUCCESS")
        self.assertEqual(job.attempts, 2)

    def test_second_worker_is_rejected(self):
        job, path = self.job()
        errors = []
        def another():
            close_old_connections()
            try:
                run_job(job.pk)
            except BlockingIOError:
                errors.append("locked")
            finally:
                close_old_connections()
        with worker_lock():
            thread = threading.Thread(target=another)
            thread.start()
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["locked"])
