"""Régression des projections indexées : résultats, synchronisation et requêtes de liste."""

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import test_business as fixtures
from .models import CampaignGlobalControl, CampaignReview, LineReview, ReviewControlContext
from .review_import import import_bundle
from .test_sage_inventory import sign_records


def synthetic_records(folder):
    """Génère le véritable JSONL fictif Lot 1 sans auto-validation, dans un répertoire jetable."""
    root = Path(__file__).resolve().parents[2]
    subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "examples.lot1_fixture", str(folder)],
                   cwd=root, check=True, capture_output=True, timeout=60)
    records = [json.loads(row) for row in (Path(folder) / "campaign.jsonl").read_text(encoding="utf-8").splitlines()]
    for record in records:
        if record.get("type") == "proposal":
            record.pop("auto_validation", None)
    sign_records(records)
    return records


class ControlIndexTests(TestCase):
    """Compare l'index aux snapshots existants et vérifie la lecture SQL légère."""
    load = fixtures.BusinessTests.load
    inventory = fixtures.BusinessTests.inventory
    entry = fixtures.BusinessTests.entry
    confirm = fixtures.BusinessTests.confirm
    setUp = fixtures.BusinessTests.setUp

    @classmethod
    def setUpClass(cls):
        """Prépare une fois les seules sources synthétiques nécessaires aux tests."""
        super().setUpClass()
        cls.folder_sources = TemporaryDirectory()
        cls.records = synthetic_records(Path(cls.folder_sources.name))

    @classmethod
    def tearDownClass(cls):
        """Libère les fichiers temporaires de la classe, sans toucher à la base applicative."""
        cls.folder_sources.cleanup()
        super().tearDownClass()

    def test_count_and_pagination_do_not_read_json_or_correlated_subqueries(self):
        """Toutes origines : comptage et identifiants paginés restent sur les colonnes indexées.

        Le filtre Origine ciblé utilise ses présences JSON matérialisées ; ce test
        isole les filtres d'état sans cette restriction, comme avant son ajout.
        """
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("reconciliation:reviews"), {"view": "controls", "origin": ""})
        self.assertEqual(response.status_code, 200)
        # L'unique requête d'options de types est distincte des comptages et
        # lectures paginées, dont le budget et l'absence de calcul restent vérifiés.
        type_options = [query["sql"] for query in queries if 'AS "filter_piece_type"' in query["sql"]]
        self.assertEqual(len(type_options), 1)
        control_queries = [query["sql"] for query in queries if 'FROM "reconciliation_campaignglobalcontrol"' in query["sql"]
                           and 'AS "filter_piece_type"' not in query["sql"]]
        self.assertTrue(any("COUNT(" in sql for sql in control_queries))
        for sql in control_queries:
            if "COUNT(" in sql or "LIMIT" in sql:
                self.assertNotIn("JSON_", sql)
                self.assertNotIn("COALESCE", sql)
            self.assertNotIn("EXISTS", sql)
            self.assertNotIn("CASE WHEN", sql)
        full_queries = [sql for sql in control_queries if "COALESCE" in sql]
        self.assertEqual(len(full_queries), 1)
        self.assertIn('"id" IN', full_queries[0])

    def test_confirm_and_cancel_update_pending_in_same_transaction(self):
        """Une validation retire l'alerte puis son annulation la rétablit sans reconstruction globale."""
        from .business import cancel_inventory_link
        control = self.campaign.global_controls.get(key=self.entry().control_key)
        self.assertTrue(control.has_pending)
        self.confirm()
        control.refresh_from_db()
        self.assertFalse(control.has_pending)
        self.assertEqual(control.current_state, "EQUILIBRE")
        row = self.inventory()
        cancel_inventory_link(row.pk, self.user, expected_version=row.business_version, comment="Révision")
        control.refresh_from_db()
        self.assertTrue(control.has_pending)
        self.assertEqual(control.current_state, "ECART")

    def test_removed_context_refreshes_both_old_and_new_keys(self):
        """Le déplacement d'un contexte retire l'ancienne alerte et crée la nouvelle."""
        review = self.campaign.reviews.select_related("project").get(source__source_id="S")
        old_key = self.entry().control_key
        new_key = self.campaign.sage_inventory.get(document="FAC999").control_key
        review.decision["multiple_context"]["controls"] = {new_key: "test"}
        review.save(update_fields=["decision"])
        self.assertFalse(self.campaign.global_controls.get(key=old_key).has_pending)
        self.assertTrue(self.campaign.global_controls.get(key=new_key).has_pending)
        self.assertEqual(set(review.control_contexts.values_list("key", flat=True)), {new_key})

    def test_another_pending_review_keeps_the_alert(self):
        """La confirmation d'une ligne ne masque pas une autre proposition du même contrôle."""
        first = self.campaign.reviews.select_related("line__transaction", "project", "group").get(source__source_id="S")
        item = first.line.transaction
        item.pk, item.business_key, item.source_id = None, "SECOND", "SECOND"
        item.save(force_insert=True)
        line = LineReview.objects.create(transaction=item, campaign=self.campaign, group=first.line.group)
        other = CampaignReview.objects.create(campaign=self.campaign, project=first.project, group=first.group,
            line=line, source=first.source, decision={"state": "DRAFT", "current": False,
                "multiple_context": first.decision["multiple_context"]}, fingerprint="")
        self.confirm()
        control = self.campaign.global_controls.get(key=self.entry().control_key)
        self.assertTrue(control.has_pending)
        other.decision.update(state="VALIDATED", current=True)
        other.save(update_fields=["decision"])
        control.refresh_from_db()
        self.assertFalse(control.has_pending)

    def test_rebuilding_index_is_idempotent_and_does_not_touch_decisions(self):
        """Une reconstruction technique conserve les décisions, résultats et versions métier."""
        from .control_index import rebuild_campaign
        decisions = list(self.campaign.reviews.values_list("pk", "decision"))
        controls = list(self.campaign.global_controls.values_list("pk", "data", "current_data", "current_version"))
        count = self.campaign.review_control_contexts.count()
        rebuild_campaign(self.campaign)
        rebuild_campaign(self.campaign)
        self.assertEqual(self.campaign.review_control_contexts.count(), count)
        self.assertEqual(list(self.campaign.reviews.values_list("pk", "decision")), decisions)
        self.assertEqual(list(self.campaign.global_controls.values_list("pk", "data", "current_data", "current_version")), controls)


class ControlIndexMigrationTests(TransactionTestCase):
    """Vérifie le peuplement initial sur des photographies réellement importées avant migration."""

    def test_existing_campaign_backfill_preserves_business_data(self):
        """0021 remplit les index depuis 0020 sans changer snapshot, décision ou état initial."""
        from .models import Campaign
        with TemporaryDirectory() as folder:
            records = synthetic_records(Path(folder))
            path = Path(folder) / "before.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
            import_bundle(path)
        campaign = Campaign.objects.get(is_current=True)
        reviews = list(campaign.reviews.values_list("pk", "decision"))
        controls = list(campaign.global_controls.values_list("pk", "data", "current_data", "state"))
        expected = list(campaign.global_controls.order_by("pk").values_list("current_state", "has_pending"))
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([("reconciliation", "0020_lot2_business_actions")])
            executor = MigrationExecutor(connection)
            executor.migrate([("reconciliation", "0021_control_workspace_indexes")])
            self.assertEqual(list(campaign.reviews.values_list("pk", "decision")), reviews)
            self.assertEqual(list(campaign.global_controls.values_list("pk", "data", "current_data", "state")), controls)
            self.assertEqual(list(campaign.global_controls.order_by("pk").values_list("current_state", "has_pending")), expected)
            self.assertTrue(ReviewControlContext.objects.filter(campaign=campaign).exists())
        finally:
            latest = MigrationExecutor(connection)
            latest.migrate(latest.loader.graph.leaf_nodes())
