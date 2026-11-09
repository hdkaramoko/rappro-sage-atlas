"""Comparaison exacte des prototypes privés avec le calcul nominal, sur sources synthétiques."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.db import connection
from django.test import TestCase

from benchmarks.profile_accounting import canonical_digest, preload_inputs, run_project
from . import accounting
from . import test_business as fixtures
from .accounting_models import AccountingProject
from .test_control_index import synthetic_records


class AccountingAuditTests(TestCase):
    """Vérifie idempotence, absence de mutation métier et atomicité des variantes de diagnostic."""

    load = fixtures.BusinessTests.load
    setUp = fixtures.BusinessTests.setUp

    @classmethod
    def setUpClass(cls):
        """Prépare les seules sources fictives nécessaires dans un dossier temporaire."""
        super().setUpClass()
        cls.folder_sources = TemporaryDirectory()
        cls.records = synthetic_records(Path(cls.folder_sources.name))

    @classmethod
    def tearDownClass(cls):
        """Libère le dossier de recette sans toucher aux bases ou fichiers utilisateur."""
        cls.folder_sources.cleanup()
        super().tearDownClass()

    def test_prototypes_preserve_every_project_and_group_field(self):
        """Tous les prototypes conservent les chiffres, types et motifs, y compris le fallback JSON vide."""
        original = accounting.refresh_project
        source = list(self.campaign.inventory.values_list("pk", "data"))
        decisions = list(self.campaign.reviews.values_list("pk", "decision"))
        control = self.campaign.global_controls.first()
        control.current_data = {}
        control.save(update_fields=["current_data"])
        for variant in ("baseline", "batch500", "batch1000", "bulk500", "collisions_once", "preload", "lean", "batch_bulk", "combined"):
            cache = preload_inputs(self.campaign, ["P"], variant) if variant in ("collisions_once", "preload") else None
            result = run_project(connection, self.campaign, "P", variant, cache)
            self.assertTrue(result["unchanged"], variant)
            self.assertIs(accounting.refresh_project, original)
        self.assertEqual(list(self.campaign.inventory.values_list("pk", "data")), source)
        self.assertEqual(list(self.campaign.reviews.values_list("pk", "decision")), decisions)

    def test_audit_failure_rolls_back_deleted_and_inserted_groups(self):
        """Une erreur d'upsert restaure intégralement les agrégats et le module nominal reste inchangé."""
        before = canonical_digest(self.campaign, "P")
        original = accounting.refresh_project
        with patch.object(AccountingProject.objects, "update_or_create", side_effect=RuntimeError("Recette rollback")):
            with self.assertRaises(RuntimeError):
                run_project(connection, self.campaign, "P", "baseline", None)
        self.assertEqual(canonical_digest(self.campaign, "P"), before)
        self.assertIs(accounting.refresh_project, original)
