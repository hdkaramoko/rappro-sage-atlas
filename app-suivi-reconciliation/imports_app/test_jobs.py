import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import User

from .jobs import job_directory, run_job, worker_lock
from .models import MatchingJob


class ManualImportTests(TransactionTestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        override = override_settings(MATCHING_JOB_ROOT=Path(self.folder.name))
        override.enable()
        self.addCleanup(override.disable)
        self.admin = User.objects.create_user("admin", is_staff=True)
        self.client.force_login(self.admin)

    def upload(self, content=b'{"complete": 0}\n', name="resultats.jsonl"):
        return self.client.post(
            reverse("imports:index"),
            {
                "bundle": SimpleUploadedFile(name, content),
            },
        )

    @patch("imports_app.views.launch")
    def test_upload_and_duplicate(self, launch):
        response = self.upload()
        job = MatchingJob.objects.get()
        self.assertRedirects(response, reverse("imports:detail", args=[job.pk]))
        self.assertEqual(job.file_hash, hashlib.sha256(b'{"complete": 0}\n').hexdigest())
        launch.assert_called_once()
        self.assertContains(self.upload(), "déjà en cours")
        with patch("imports_app.jobs.subprocess.Popen") as process:
            run_job(job.pk)
            process.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.state, "SUCCESS")
        self.upload()
        duplicate = MatchingJob.objects.exclude(pk=job.pk).get()
        with patch("imports_app.jobs.import_bundle") as importer:
            run_job(duplicate.pk)
            importer.assert_not_called()
        duplicate.refresh_from_db()
        self.assertEqual(duplicate.state, "DUPLICATE")
        self.assertFalse(duplicate.active)

    @patch("imports_app.views.launch")
    def test_invalid_file_rolls_back_and_releases_slot(self, launch):
        self.upload(b'{"schema_version": 999}\n')
        job = MatchingJob.objects.get()
        run_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, "FAILED")
        self.assertFalse(job.active)
        self.assertTrue(job.error)

    @patch("imports_app.views.launch", side_effect=OSError("Indisponible"))
    def test_launch_failure(self, launch):
        self.upload()
        job = MatchingJob.objects.get()
        self.assertEqual(job.state, "FAILED")
        self.assertFalse(job.active)

    def test_extension_size_and_permissions(self):
        self.assertContains(self.upload(name="atlas.xlsx"), "fichier .jsonl")
        with override_settings(MATCHING_MAX_FILE_BYTES=1):
            self.assertContains(self.upload(), "taille maximale")
        user = User.objects.create_user("reader")
        self.client.force_login(user)
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.client.get(reverse("imports:index")).status_code, 403)
        self.assertEqual(MatchingJob.objects.count(), 0)

    @patch("imports_app.views.launch")
    def test_resume_and_download_permissions(self, launch):
        self.upload()
        job = MatchingJob.objects.get()
        job.state = "IMPORTING"
        job.save()
        run_job(job.pk, resume=True)
        job.refresh_from_db()
        self.assertEqual(job.state, "SUCCESS")
        url = reverse("imports:download", args=[job.pk, "propositions"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.force_login(User.objects.create_user("reader"))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("imports:detail", args=[job.pk])).status_code, 403)
        self.assertTrue((job_directory(job) / "import.log").exists())

    def test_worker_is_serialized(self):
        with worker_lock(), self.assertRaises(OSError), worker_lock():
            pass

    @patch("imports_app.views.launch")
    def test_file_changed_after_upload_is_rejected(self, launch):
        self.upload()
        job = MatchingJob.objects.get()
        (job_directory(job) / "propositions.jsonl").write_text('{"complete": 1}\n')
        run_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, "FAILED")
        self.assertIn("changé depuis son transfert", job.error)
