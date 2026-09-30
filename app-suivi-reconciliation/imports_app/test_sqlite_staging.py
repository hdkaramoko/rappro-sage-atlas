"""Exécute les scénarios disque dans un processus indépendant de la base des tests Django."""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


class SQLiteStagingTests(SimpleTestCase):
    def test_real_file_database(self):
        """Vérifie publication, reprise et concurrence avec de vraies connexions SQLite."""
        with TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, "-m", "imports_app.sqlite_scenarios", folder],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=240,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
