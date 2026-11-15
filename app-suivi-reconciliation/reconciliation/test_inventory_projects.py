"""Exhaustivité du référentiel importé, conservation et droits des projets sans proposition."""

import copy
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from reconciliation_contract import control_identity, snapshot
from reconciliation_contract.atlas_context import ATLAS_CONTEXT

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from . import test_campaigns as fixtures
from .accounting_models import AccountingProject
from .campaigns import normalize_inventory
from .models import Campaign, LineReview
from .review_import import import_bundle
from .test_campaigns import atlas, proposal
from .test_control_index import synthetic_records
from .test_sage_inventory import sign_records


class InventoryProjectTests(TestCase):
    """Importe des campagnes réelles sur une base de test sans référentiel préalable."""

    bundle = fixtures.CampaignTests.bundle
    load = fixtures.CampaignTests.load

    def setUp(self):
        """Isole les fichiers JSONL ; aucun projet ni portefeuille n'est précréé."""
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.rows = [
            atlas(),
            atlas("B", **{"Code projet": "Q", "Statut BAP": "Comptabilisé"}),
            atlas("C", **{"Code projet": "R", "Statut BAP": "Comptabilisé"}),
        ]

    def import_three(self):
        """Retourne une campagne avec trois projets et une seule proposition réelle."""
        return self.load(inventory=self.rows, proposals=[proposal([self.rows[0]])])

    def test_complete_reference_and_successive_imports(self):
        """Les projets sans proposition existent dès le premier import, sans doublon ensuite."""
        for _ in range(2):
            campaign = self.import_three()
            self.assertSetEqual(
                set(Project.objects.values_list("code", flat=True)), {"P", "Q", "R"}
            )
            self.assertEqual(campaign.inventory.count(), 3)
            self.assertEqual(campaign.reviews.count(), 1)
            self.assertEqual(LineReview.objects.count(), 1)
            self.assertFalse(ProjectPortfolio.objects.exists())

    def test_existing_projects_are_untouched(self):
        """Libellé, géographie, désactivation, dates et portefeuille existants sont préservés."""
        project = Project.objects.create(
            code="Q", label="Libellé conservé", geography="Zone", is_active=False
        )
        user = User.objects.create_user("owner")
        portfolio = ProjectPortfolio.objects.create(user=user, project=project)
        before = Project.objects.filter(pk=project.pk).values().get()
        self.import_three()
        self.assertEqual(Project.objects.filter(pk=project.pk).values().get(), before)
        self.assertEqual(ProjectPortfolio.objects.get().pk, portfolio.pk)

    def test_normalized_codes_across_inventory_batches(self):
        """Les codes validés sont normalisés et dédupliqués même entre plusieurs lots."""
        rows = [
            atlas(str(i), **{"Code projet": code, "Statut BAP": "Comptabilisé"})
            for i, code in enumerate((" q ", "Q", "r", "S", "s "))
        ]
        with patch("reconciliation.campaigns.BATCH_SIZE", 2):
            self.load(inventory=rows, proposals=[])
        self.assertSetEqual(set(Project.objects.values_list("code", flat=True)), {"Q", "R", "S"})

    def test_v3_inventory_only_projects_preserve_accounting(self):
        """Le flux v3 crée les projets sans proposition et conserve le cadrage existant."""
        records = synthetic_records(Path(self.folder.name))
        path = Path(self.folder.name) / "v3.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        import_bundle(path)
        baseline = AccountingProject.objects.get(campaign__is_current=True, project_code="P")
        before = (baseline.atlas, baseline.sage, baseline.gap, baseline.state, baseline.data)
        original = next(
            row["atlas"]
            for row in records
            if row.get("type") == "inventory" and row["atlas"]["Statut BAP"] == "Comptabilisé"
        )
        for code in ("Q", "R"):
            raw = {**copy.deepcopy(original), "Code projet": code}
            data = normalize_inventory(
                raw, extended=True, ods_label_policy=records[0].get("ods_label_policy")
            )
            data = {
                key: value
                for key, value in data.items()
                if key not in (*ATLAS_CONTEXT.values(), "display_bap")
            }
            records.insert(1, {"type": "inventory", "atlas": raw})
            control = snapshot(
                control_identity(data),
                [data],
                [],
                amount_field=records[0]["amount_field"],
                tolerance=records[0]["tolerance"],
            )
            records.insert(-1, {"type": "control", "data": control})
        records[0]["name"] = "Trois projets v3"
        records[-1]["inventory_count"] += 2
        records[-1]["control_count"] += 2
        records[-1]["control_statuses"] = dict(
            Counter(row["data"]["status"] for row in records if row.get("type") == "control")
        )
        sign_records(records)
        path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        import_bundle(path)
        self.assertSetEqual(set(Project.objects.values_list("code", flat=True)), {"P", "Q", "R"})
        self.assertFalse(
            Campaign.objects.get(is_current=True).reviews.exclude(project__code="P").exists()
        )
        after = AccountingProject.objects.get(campaign__is_current=True, project_code="P")
        self.assertEqual((after.atlas, after.sage, after.gap, after.state, after.data), before)

    def test_invalid_import_rolls_back_new_projects(self):
        """Une erreur après synchronisation annule les créations et conserve la campagne publiée."""
        first = self.load()
        for complete in (False, True):
            invalid = proposal([atlas("absent")]) if complete else proposal([self.rows[0]])
            with self.subTest(complete=complete), self.assertRaises(ValidationError):
                self.load(inventory=self.rows, proposals=[invalid], complete=complete)
            self.assertEqual(list(Project.objects.values_list("code", flat=True)), ["P"])
            self.assertEqual(Campaign.objects.get(is_current=True).pk, first.pk)
            self.assertEqual(Campaign.objects.count(), 1)

    def test_reference_queries_follow_batches_not_inventory_rows(self):
        """Des centaines de lignes répétées n'ajoutent aucune lecture SQL par ligne/projet."""
        rows = [
            atlas(str(i), **{"Code projet": f"P{i % 30:02}", "Statut BAP": "Comptabilisé"})
            for i in range(600)
        ]
        with CaptureQueriesContext(connection) as queries:
            campaign = self.load(inventory=rows, proposals=[])
        self.assertEqual(Project.objects.count(), 30)
        self.assertEqual(campaign.inventory.count(), 600)
        reads = [q for q in queries if 'FROM "projects_project"' in q["sql"]]
        self.assertEqual(len(reads), 2)

    def test_admin_visibility_and_user_access(self):
        """Un admin voit le cadrage sans proposition ; un compte sans portefeuille reste exclu."""
        campaign = self.import_three()
        summary = AccountingProject.objects.get(campaign=campaign, project_code="Q")
        before = (summary.atlas, summary.sage, summary.gap, summary.state)
        inventory = campaign.inventory.get(project_code="Q")
        admin = User.objects.create_user("admin", is_staff=True)
        self.client.force_login(admin)
        dashboard = self.client.get(reverse("dashboard:index"))
        self.assertEqual(dashboard.context["projects_count"], 3)
        response = self.client.get(reverse("reconciliation:accounting-list"))
        self.assertEqual(response.context["page"].paginator.count, 3)
        detail = reverse("reconciliation:accounting-detail", args=[summary.pk])
        self.assertEqual(self.client.get(detail).status_code, 200)
        user = User.objects.create_user("without-portfolio")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("dashboard:index")).context["projects_count"], 0)
        self.assertEqual(self.client.get(detail).status_code, 404)
        source_url = reverse("reconciliation:inventory-detail", args=[inventory.pk])
        self.assertEqual(self.client.get(source_url).status_code, 404)
        self.assertIn(self.client.post(source_url, {}).status_code, (403, 404, 405))
        summary.refresh_from_db()
        self.assertEqual((summary.atlas, summary.sage, summary.gap, summary.state), before)

    def test_synchronization_failure_rolls_back(self):
        """Un échec de création groupée ne laisse ni campagne ni projet partiel."""
        with patch(
            "reconciliation.campaigns.Project.objects.bulk_create",
            side_effect=ValidationError("échec"),
        ):
            with self.assertRaises(ValidationError):
                self.import_three()
        self.assertFalse(Project.objects.exists())
        self.assertFalse(Campaign.objects.exists())
