"""Régression des champs budgétaires trop longs lors de l'import PostgreSQL."""

from django.db import connection
from django.test import TestCase

from . import test_campaigns as fixtures
from .models import Campaign, ImportRevision, ReconciliationTransaction
from .review_import import import_bundle


class BudgetLineImportTests(TestCase):
    """Importe des sources synthétiques longues en préservant les photographies."""

    setUp = fixtures.CampaignTests.setUp
    bundle = fixtures.CampaignTests.bundle

    def import_budget(self, code: str, label: str):
        """Importe un JSONL avec `code`/`label` budgétaires et retourne la campagne.

        Les textes sont conservés intégralement ; les écritures se limitent à
        la base de test. Une erreur de validation ou SQL annule l'import parent.
        """
        row = fixtures.atlas(**{"Code ligne budgétaire": code, "Libellé ligne budgétaire": label})
        import_bundle(self.bundle(inventory=[row], proposals=[fixtures.proposal([row])]))
        return Campaign.objects.get(is_current=True)

    def test_long_budget_values_import_without_truncation(self):
        """Préserve un code de 142 caractères et un libellé de 753, limites du cas réel."""
        code = "B" * 142
        label = "É" * 753
        campaign = self.import_budget(code, label)
        item = ReconciliationTransaction.objects.get()
        item.full_clean()
        self.assertEqual(item.budget_line_code, code)
        self.assertEqual(item.budget_line_label, label)
        self.assertEqual(campaign.reviews.get().source["budget_line_code"], code)
        self.assertEqual(campaign.reviews.get().source["budget_line_label"], label)

    def test_long_budget_values_preserve_old_campaign_and_revision_protection(self):
        """Une nouvelle source longue ne réécrit pas l'ancienne photographie.

        Vérifie aussi que les triggers SQLite de révision survivent à la
        migration des deux champs ; PostgreSQL conserve son circuit transactionnel.
        """
        first = self.import_budget("B1", "Libellé court")
        self.import_budget("B" * 142, "É" * 753)
        self.assertEqual(first.reviews.get().source["budget_line_code"], "B1")
        self.assertEqual(first.reviews.get().source["budget_line_label"], "Libellé court")
        if connection.vendor == "sqlite":
            revision = ImportRevision.objects.get(pk=1).revision
            ReconciliationTransaction.objects.update(budget_line_label="Modification de recette")
            self.assertGreater(ImportRevision.objects.get(pk=1).revision, revision)
