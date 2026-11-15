"""Initialisation des diagnostics existants, sans reprise des décisions financières."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from .incomplete_accounting import missing_mask


class IncompleteMigrationTests(TransactionTestCase):
    """Vérifie la migration sur une campagne courante et une photographie historique."""

    def test_current_only_backfill_preserves_sources_and_results(self):
        """Matérialise les seuls diagnostics courants ; sources et calculs sont inchangés."""
        old_target = [("reconciliation", "0026_campaign_poles")]
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(old_target)
            state = executor.loader.project_state(old_target).apps
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND "
                        "(tbl_name='reconciliation_campaigninventory' OR "
                        "tbl_name='reconciliation_campaignglobalcontrol')"
                    )
                    self.assertEqual(cursor.fetchone()[0], 6)
            Campaign = state.get_model("reconciliation", "Campaign")
            Inventory = state.get_model("reconciliation", "CampaignInventory")
            Control = state.get_model("reconciliation", "CampaignGlobalControl")
            key = "a" * 64
            data = {
                "bap_status": "Comptabilisé",
                "total_sage_charges": None,
                "sage_document_number": "",
                "accounting_date": None,
            }
            identities = []
            for current in (False, True):
                campaign = Campaign.objects.create(
                    name=str(current), scope="test", is_current=current
                )
                source = Inventory.objects.create(
                    campaign=campaign,
                    project_code="P",
                    source_id="A",
                    fiscal_year=2026,
                    business_key="P::2026::A",
                    control_key=key,
                    data=data,
                )
                control = Control.objects.create(
                    campaign=campaign,
                    project_code="P",
                    key=key,
                    state="INDETERMINE",
                    data={"state": "INDETERMINE", "gap": None},
                )
                identities.append((source.pk, control.pk))
            executor = MigrationExecutor(connection)
            executor.migrate([("reconciliation", "0027_incomplete_accounting_diagnostics")])
            from .models import CampaignGlobalControl, CampaignInventory

            for current, (source_pk, control_pk) in zip((False, True), identities, strict=True):
                source = CampaignInventory.objects.get(pk=source_pk)
                control = CampaignGlobalControl.objects.get(pk=control_pk)
                self.assertEqual(source.data, data)
                self.assertEqual(
                    source.sage_missing_mask, missing_mask(data, 2026) if current else 0
                )
                self.assertEqual(control.sage_incomplete_count, int(current))
                self.assertEqual(control.data, {"state": "INDETERMINE", "gap": None})
                self.assertEqual(control.state, "INDETERMINE")
            if connection.vendor == "sqlite":
                Revision = state.get_model("reconciliation", "ImportRevision")
                revision, _ = Revision.objects.get_or_create(pk=1)
                before = revision.revision
                CampaignInventory.objects.filter(pk=identities[-1][0]).update(business_version=1)
                revision.refresh_from_db()
                self.assertGreater(revision.revision, before)
        finally:
            latest = MigrationExecutor(connection)
            latest.migrate(latest.loader.graph.leaf_nodes())
