"""Recette de migration des seuls diagnostics collectifs courants."""

import copy
from importlib import import_module

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase
from reconciliation_contract import digest

from .test_global_currency import old_diagnostic

migration = import_module("reconciliation.migrations.0023_group_signed_amounts")


class SignedDiagnosticTests(SimpleTestCase):
    """Les anciens vetos disparaissent sans effacer les autres motifs ou décisions."""

    def test_signed_results_keep_gaps_guards_and_history(self):
        """Le nettoyage est signé, idempotent et respecte écarts, exclusions et données absentes."""
        data = old_diagnostic(reasons=sorted(migration.OBSOLETE_REASONS))
        data["accounted_reasons"] = list(data["reasons"])
        before = copy.deepcopy(data)
        result = migration.normalize_current(data)
        self.assertEqual(result["state"], "EQUILIBRE")
        self.assertFalse(result["auto_validated"])
        self.assertEqual(data, before)
        self.assertEqual(result["signature"], digest({k: v for k, v in result.items() if k != "signature"}))
        self.assertIsNone(migration.normalize_current(result))
        for gap, extra, previous, expected in [("2", [], "INDETERMINE", "ECART"),
                (None, [], "INDETERMINE", "INDETERMINE"),
                ("0", ["Identité ambiguë"], "INDETERMINE", "INDETERMINE"),
                ("0", [], "EXCLU", "EXCLU")]:
            variant = {**data, "gap": gap, "reasons": data["reasons"] + extra, "state": previous}
            self.assertEqual(migration.normalize_current(variant)["state"], expected)


class SignedMigrationTests(TransactionTestCase):
    """La pagination met à jour les diagnostics actifs sans toucher à l'historique."""

    def test_active_results_only_across_batches(self):
        """Plus de 250 résultats sont corrigés une seule fois ; sources et décisions restent intactes."""
        executor = MigrationExecutor(connection)
        executor.migrate([("reconciliation", "0022_global_control_eur_charges")])
        apps = executor.loader.project_state([("reconciliation", "0022_global_control_eur_charges")]).apps
        Campaign = apps.get_model("reconciliation", "Campaign")
        Control = apps.get_model("reconciliation", "CampaignGlobalControl")
        active = Campaign.objects.create(name="Actif sommes signées", scope="test", is_current=True)
        closed = Campaign.objects.create(name="Historique sommes signées", scope="test", is_current=False)
        data = old_diagnostic(reasons=sorted(migration.OBSOLETE_REASONS))
        data["accounted_reasons"] = list(data["reasons"])
        Control.objects.bulk_create([Control(campaign=active, key=f"{i:064x}", project_code="P", data=data,
            state="INDETERMINE", current_state="INDETERMINE", has_pending=True) for i in range(251)])
        history = Control.objects.create(campaign=closed, key="f" * 64, project_code="P", data=data,
            state="INDETERMINE", current_state="INDETERMINE")
        try:
            MigrationExecutor(connection).migrate([("reconciliation", "0023_group_signed_amounts")])
            self.assertEqual(Control.objects.filter(campaign=active, current_state="EQUILIBRE").count(), 251)
            row = Control.objects.filter(campaign=active).first()
            self.assertEqual(row.data, data)
            self.assertEqual(row.state, "INDETERMINE")
            self.assertTrue(row.has_pending)
            self.assertFalse(row.current_data["auto_validated"])
            history.refresh_from_db()
            self.assertIsNone(history.current_data)
            with transaction.atomic():
                migration.correct_active_diagnostics(apps, connection.schema_editor())
            self.assertEqual(Control.objects.filter(campaign=active, current_version=1).count(), 251)
        finally:
            latest = MigrationExecutor(connection)
            latest.migrate(latest.loader.graph.leaf_nodes())
