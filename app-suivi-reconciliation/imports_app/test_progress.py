"""Le suivi sur disque ne doit pas interrompre une importation métier."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from .progress import ImportProgress, read_progress_file


class ProgressTests(SimpleTestCase):
    def setUp(self):
        """Isole les fichiers de suivi des véritables imports."""
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.progress = ImportProgress(self.path)

    def test_temporary_windows_lock_retries(self):
        """Un refus transitoire est suivi d'un remplacement atomique réussi."""
        replace = os.replace
        attempts = 0

        def locked_once(source, target):
            """Simule une lecture Windows concurrente au premier remplacement."""
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise PermissionError(5, "Accès refusé")
            replace(source, target)

        with (
            patch("imports_app.progress.os.replace", side_effect=locked_once),
            patch("imports_app.progress.time.sleep"),
        ):
            self.progress("Inventaire", 500)
        self.assertEqual(attempts, 2)
        self.assertEqual(read_progress_file(self.path)["completed"], 500)

    def test_persistent_lock_keeps_last_snapshot_and_recovers(self):
        """Un verrou persistant conserve l'ancien JSON et permet la mesure suivante."""
        self.progress("Inventaire", 500)
        with (
            patch(
                "imports_app.progress.os.replace", side_effect=PermissionError(5, "Accès refusé")
            ) as replace,
            patch("imports_app.progress.time.sleep"),
        ):
            self.progress("Inventaire", 1000)
        self.assertEqual(replace.call_count, 3)
        self.assertEqual(read_progress_file(self.path)["completed"], 500)
        last = json.loads((self.path / "import.log").read_text(encoding="utf-8").splitlines()[-1])
        self.assertIn("progress_warning", last)
        self.progress("Inventaire", 1500)
        self.assertEqual(read_progress_file(self.path)["completed"], 1500)

    def test_unavailable_tracking_directory_is_nonfatal(self):
        """L'échec simultané du JSON et du journal ne remonte pas au worker."""
        progress = ImportProgress(self.path / "absent")
        progress("Publication", 10)
        self.assertEqual(progress.completed, 10)
