from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ReconciliationBackfillMigrationTests(TransactionTestCase):
    """Vérifie la reprise d'une transaction représentative depuis le schéma initial."""

    migrate_from = ("reconciliation", "0001_initial")
    migrate_to = ("reconciliation", "0005_alter_reconciliationtransaction_atlas_amount_and_more")

    def setUp(self) -> None:
        """Crée une ligne historique puis exécute toutes les migrations d'évolution."""
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        Project = old_apps.get_model("projects", "Project")
        Transaction = old_apps.get_model("reconciliation", "ReconciliationTransaction")
        project = Project.objects.create(code="RW-MIG", label="Projet migré")
        Transaction.objects.create(
            project=project,
            business_key="RW-MIG::OLD-1",
            reference="OLD-1",
            label="Dépense historique",
            transaction_date=date(2025, 12, 31),
            atlas_amount=Decimal("120.50"),
            sage_amount=Decimal("100.25"),
            atlas_status_source="ENVOYE",
            sage_status="COMPTABILISE",
            business_status_override="VALIDE",
        )
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self) -> None:
        """Restaure l'état de migration courant pour les tests suivants."""
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_legacy_values_and_correction_are_preserved(self) -> None:
        """Le backfill conserve sources, montants, suggestion et correction active."""
        Transaction = self.apps.get_model("reconciliation", "ReconciliationTransaction")
        item = Transaction.objects.get(source_id="OLD-1")
        self.assertEqual(item.fiscal_year, 2025)
        self.assertEqual(item.atlas_label, "Dépense historique")
        self.assertEqual(item.total_project_charges, Decimal("120.50"))
        self.assertEqual(item.suggestion_bap_status, "COMPTABILISE")
        self.assertTrue(item.correction_active)
        self.assertEqual(item.correction_bap_status, "VALIDE")
