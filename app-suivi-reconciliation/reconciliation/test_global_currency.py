"""Correction ciblée des diagnostics de devise, sans rejeu des décisions historiques."""

import copy
from importlib import import_module

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase
from reconciliation_contract import digest

migration = import_module("reconciliation.migrations.0022_global_control_eur_charges")


def old_diagnostic(*, gap="0.00", reasons=None):
    """Reconstitue le diagnostic signé d'avant correction pour une charge négative EUR."""
    data = {"state": "INDETERMINE", "accounted_state": "INDETERMINE", "reasons": reasons or [migration.OBSOLETE_REASON],
            "accounted_reasons": [migration.OBSOLETE_REASON], "accounted_total": "-372.41", "sage_total": "-372.41",
            "confirmed_sent_total": "0", "gap": gap, "accounted_gap": gap, "tolerance": "0.01", "auto_validated": False}
    return {**data, "signature": digest(data)}


class CurrencyDiagnosticTests(SimpleTestCase):
    """États, signatures et prudence du correctif des seuls résultats courants."""

    def test_only_currency_reason_becomes_balanced_without_auto_revalidation(self):
        """Le solde nul devient équilibré sans changer les montants ni le drapeau AUTO antérieur."""
        original = old_diagnostic()
        before = copy.deepcopy(original)
        result = migration.normalize_current(original)
        self.assertEqual(original, before)
        self.assertEqual(result["state"], "EQUILIBRE")
        self.assertEqual(result["accounted_state"], "EQUILIBRE")
        self.assertFalse(result["auto_validated"])
        self.assertEqual(result["accounted_total"], "-372.41")
        self.assertEqual(result["signature"], digest({k: v for k, v in result.items() if k != "signature"}))
        self.assertIsNone(migration.normalize_current(result))

    def test_other_reasons_gaps_and_exclusions_remain(self):
        """Un écart, un motif restant ou une exclusion ne deviennent pas artificiellement réconciliés."""
        result = migration.normalize_current(old_diagnostic(gap="2.41"))
        self.assertEqual(result["state"], "ECART")
        result = migration.normalize_current(old_diagnostic(reasons=[migration.OBSOLETE_REASON, "Écriture ambiguë"]))
        self.assertEqual(result["state"], "INDETERMINE")
        self.assertEqual(result["reasons"], ["Écriture ambiguë"])
        excluded = old_diagnostic()
        excluded["state"] = "EXCLU"
        self.assertEqual(migration.normalize_current(excluded)["state"], "EXCLU")
        self.assertEqual(migration.monetary_state("INDETERMINE", [], None, "0.01"), "INDETERMINE")


class CurrencyMigrationTests(TransactionTestCase):
    """Le traitement par lots ne modifie que les diagnostics actifs concernés."""

    def test_existing_current_results_only_are_updated_once(self):
        """Plus de 250 diagnostics sont corrigés sans omission, initial ni campagne close modifiés."""
        executor = MigrationExecutor(connection)
        executor.migrate([("reconciliation", "0021_control_workspace_indexes")])
        apps = executor.loader.project_state([("reconciliation", "0021_control_workspace_indexes")]).apps
        Campaign = apps.get_model("reconciliation", "Campaign")
        Control = apps.get_model("reconciliation", "CampaignGlobalControl")
        active = Campaign.objects.create(name="Active devise", scope="test", is_current=True)
        closed = Campaign.objects.create(name="Historique devise", scope="test", is_current=False)
        data = old_diagnostic()
        controls = [Control(campaign=active, key=f"{index:064x}", project_code="P", data=data,
                    state="INDETERMINE", current_state="INDETERMINE", has_pending=False) for index in range(260)]
        Control.objects.bulk_create(controls)
        untouched = Control.objects.create(campaign=closed, key="a" * 64, project_code="P", data=data,
            state="INDETERMINE", current_state="INDETERMINE", has_pending=False)
        pending = Control.objects.create(campaign=active, key="b" * 64, project_code="P", data=data,
            state="INDETERMINE", current_state="INDETERMINE", has_pending=True)
        try:
            MigrationExecutor(connection).migrate([("reconciliation", "0022_global_control_eur_charges")])
            self.assertEqual(Control.objects.filter(campaign=active, current_state="EQUILIBRE").count(), 261)
            row = Control.objects.filter(campaign=active).first()
            self.assertEqual(row.data, data)
            self.assertEqual(row.state, "INDETERMINE")
            self.assertEqual(row.current_version, 1)
            pending.refresh_from_db()
            self.assertTrue(pending.has_pending)
            untouched.refresh_from_db()
            self.assertIsNone(untouched.current_data)
            self.assertEqual(untouched.data, data)
            with transaction.atomic():
                migration.correct_active_diagnostics(apps, connection.schema_editor())
            self.assertEqual(Control.objects.filter(campaign=active, current_version=1).count(), 261)
        finally:
            MigrationExecutor(connection).migrate([("reconciliation", "0022_global_control_eur_charges")])
