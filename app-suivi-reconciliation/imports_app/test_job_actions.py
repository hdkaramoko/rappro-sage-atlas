"""Permissions, transitions, conservation des sources et rétention explicite."""

from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from reconciliation.models import Campaign
from .jobs import worker_lock
from .models import MatchingJob


class JobActionTests(TransactionTestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        override = override_settings(MATCHING_JOB_ROOT=self.root, MATCHING_RETENTION_DAYS=1)
        override.enable()
        self.addCleanup(override.disable)
        self.admin = User.objects.create_user("admin", is_staff=True)
        self.client.force_login(self.admin)
        self.job = MatchingJob.objects.create(bundle_name="test.jsonl", state="RETRYABLE", active=False)
        self.directory = self.root / str(self.job.pk)
        self.directory.mkdir()
        (self.directory / "propositions.jsonl").write_bytes(b'{"complete": 0}\n')

    def url(self, action):
        return reverse("imports:" + action, args=[self.job.pk])

    @patch("imports_app.views.launch")
    def test_resume_preserves_uuid_and_checkpoint_and_refuses_double_click(self, launch):
        self.job.checkpoint = {"counts": {"inventory": 500}, "section": "inventory"}
        self.job.next_offset = 10000
        self.job.save()
        self.assertEqual(self.client.get(self.url("resume")).status_code, 405)
        self.client.post(self.url("resume"))
        self.client.post(self.url("resume"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "QUEUED")
        self.assertEqual(self.job.next_offset, 10000)
        self.assertEqual(MatchingJob.objects.count(), 1)
        launch.assert_called_once()

    def test_admin_and_csrf_required(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.url("resume")).status_code, 403)
        self.client.force_login(User.objects.create_user("reader"))
        self.assertEqual(self.client.post(self.url("resume")).status_code, 403)
        self.assertEqual(self.client.post(self.url("abandon"), {"confirm": "yes"}).status_code, 403)

    def test_active_worker_blocks_resume_and_abandon(self):
        with worker_lock():
            self.client.post(self.url("resume"))
            self.client.post(self.url("abandon"), {"confirm": "yes"})
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "RETRYABLE")

    def test_abandon_requires_confirmation_and_preserves_source(self):
        self.client.post(self.url("abandon"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "RETRYABLE")
        self.client.post(self.url("abandon"), {"confirm": "yes"})
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "ABANDONED")
        self.assertFalse(self.job.active)
        self.assertTrue((self.directory / "propositions.jsonl").exists())

    def test_missing_source_incompatible_version_and_other_active_job(self):
        with patch("imports_app.views.launch") as launch:
            self.job.protocol_version = 999
            self.job.save()
            self.client.post(self.url("resume"))
            self.job.protocol_version = 1
            self.job.save()
            (self.directory / "propositions.jsonl").unlink()
            self.client.post(self.url("resume"))
            (self.directory / "propositions.jsonl").write_bytes(b'{}')
            MatchingJob.objects.create(state="QUEUED")
            self.client.post(self.url("resume"))
            launch.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, "RETRYABLE")

    def test_cleanup_dry_run_then_terminal_only(self):
        from reconciliation.campaigns import insert_inventory, normalize_inventory
        from reconciliation.test_campaigns import atlas
        stage = Campaign.all_objects.create(job=self.job, published=False, name="Stage", scope="test")
        insert_inventory(stage, [normalize_inventory(atlas())])
        self.job.state = "ABANDONED"
        self.job.finished_at = timezone.now() - timedelta(days=2)
        self.job.save()
        call_command("cleanup_matching_jobs", stdout=StringIO())
        self.assertTrue(self.directory.exists())
        call_command("cleanup_matching_jobs", apply=True, stdout=StringIO())
        self.assertFalse(self.directory.exists())
        self.assertTrue(MatchingJob.objects.filter(pk=self.job.pk).exists())
        self.assertFalse(Campaign.all_objects.filter(pk=stage.pk).exists())

    def test_historical_job_migration_preserves_completed_jobs(self):
        from importlib import import_module
        from django.db import connection
        from types import SimpleNamespace
        old = MatchingJob.objects.create(state="MATCHING", active=True)
        complete = MatchingJob.objects.create(state="SUCCESS", active=False)
        migration = import_module("imports_app.migrations.0004_durable_checkpoints")
        migration.retire_unsupported_active_jobs(apps, SimpleNamespace(connection=connection))
        old.refresh_from_db()
        complete.refresh_from_db()
        self.assertFalse(old.active)
        self.assertEqual(old.state, "FAILED")
        self.assertEqual(complete.state, "SUCCESS")
        self.assertEqual(complete.protocol_version, 0)
