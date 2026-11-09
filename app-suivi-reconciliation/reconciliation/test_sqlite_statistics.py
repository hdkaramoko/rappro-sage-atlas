"""Maintenance SQLite : transactions, compteurs, sécurité des logs et flux d'import."""

import copy
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import connection, DatabaseError, transaction
from django.test import TransactionTestCase, TestCase, override_settings

from . import test_business as fixtures
from .models import Campaign, CampaignInventory
from .sqlite_statistics import after_campaign_commit, maintain_statistics, defer_private_accounting


class SQLiteStatisticsTests(TransactionTestCase):
    """Exerce le vrai ANALYZE hors transaction sur une base de test exclusivement."""

    def setUp(self):
        """Retire les statistiques de la base jetable pour rendre chaque décision reproductible."""
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS sqlite_stat1")

    def test_missing_then_present_and_force_preserve_business_rows(self):
        """La première maintenance crée des statistiques ; les suivantes ignorent ou forcent sans mutation métier."""
        campaign = Campaign.objects.create(name="Recette statistiques", scope="test", is_current=True)
        CampaignInventory.objects.create(campaign=campaign, business_key="X", project_code="P", source_id="X", fiscal_year=2026, data={})
        before = list(Campaign.objects.values())
        first = maintain_statistics()
        self.assertEqual(first["status"], "executed")
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_stat1'")
            self.assertIsNotNone(cursor.fetchone())
            cursor.execute("SELECT 1 FROM sqlite_stat1 WHERE tbl='reconciliation_campaigninventory' AND idx IS NOT NULL LIMIT 1")
            self.assertIsNotNone(cursor.fetchone())
        self.assertEqual(maintain_statistics()["status"], "skipped")
        self.assertEqual(maintain_statistics(force=True, automatic=False)["status"], "executed")
        self.assertEqual(list(Campaign.objects.values()), before)

    def test_commit_runs_after_transaction_and_rollback_runs_nothing(self):
        """La maintenance n'est appelée qu'après commit réel ; un rollback supprime le callback."""
        observed = []

        def completed(**kwargs):
            """Relève l'état transactionnel sans effectuer de maintenance SQL supplémentaire."""
            observed.append(connection.in_atomic_block)

        with patch("reconciliation.sqlite_statistics.maintain_statistics", side_effect=completed):
            with transaction.atomic():
                after_campaign_commit()
                self.assertEqual(observed, [])
            self.assertEqual(observed, [False])
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    after_campaign_commit()
                    raise RuntimeError("Rollback de recette")
            self.assertEqual(observed, [False])

    def test_active_transaction_and_private_staging_defer_explicitly(self):
        """Une transaction interdit ANALYZE ; le staging privé utilise son séquencement explicite."""
        with transaction.atomic():
            self.assertEqual(maintain_statistics(force=True)["status"], "deferred")
        with patch("reconciliation.sqlite_statistics.maintain_statistics") as service:
            with defer_private_accounting():
                after_campaign_commit()
            service.assert_not_called()

    def test_non_sqlite_and_disabled_policy_never_issue_sql(self):
        """PostgreSQL est ignoré avant tout SQL spécifique ; la politique automatique est désactivable."""
        with patch.object(connection, "vendor", "postgresql"), patch.object(connection, "cursor") as cursor:
            self.assertEqual(maintain_statistics(force=True)["reason"], "backend_not_sqlite")
            cursor.assert_not_called()
        with override_settings(SQLITE_STATISTICS_AUTO=False), patch.object(connection, "cursor") as cursor:
            self.assertEqual(maintain_statistics(after_import=True)["reason"], "automatic_disabled")
            cursor.assert_not_called()

    def test_errors_are_explicit_and_logs_do_not_include_parameters(self):
        """Une erreur SQL produit un bilan sans message sensible ; aucun traceback ni paramètre n'est logué."""
        with patch.object(connection, "cursor", side_effect=DatabaseError("DONNEE_FINANCIERE_PRIVEE")):
            with self.assertLogs("reconciliation.sqlite_statistics", level="ERROR") as logs:
                result = maintain_statistics(force=True)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("DONNEE_FINANCIERE_PRIVEE", str(result) + str(logs.output))

    def test_explicit_command_reports_backend_and_duration(self):
        """La commande d'exploitation force la collecte et rend son motif visible."""
        output = StringIO()
        call_command("maintain_sqlite_statistics", force=True, stdout=output)
        self.assertIn("executed", output.getvalue())
        self.assertIn("forced", output.getvalue())

    def test_race_rechecks_statistics_after_writer_lock(self):
        """Si une autre maintenance vient de finir, le contrôle sous verrou évite un second ANALYZE."""
        statements = []

        def observe(execute, sql, params, many, context):
            """Relève les seuls mots SQL de la recette, puis conserve le comportement réel."""
            statements.append(sql)
            return execute(sql, params, many, context)

        with patch("reconciliation.sqlite_statistics.statistics_missing", side_effect=[True, False]), connection.execute_wrapper(observe):
            result = maintain_statistics()
        self.assertEqual(result["reason"], "statistics_present_after_lock")
        self.assertNotIn("ANALYZE", statements)
        self.assertFalse(connection.connection.in_transaction)

    def test_failure_during_analyze_releases_its_transaction(self):
        """Une erreur après BEGIN IMMEDIATE fait rollback et libère le verrou de maintenance."""
        def fail(execute, sql, params, many, context):
            """Simule une erreur uniquement sur ANALYZE ; les autres requêtes gardent leur effet réel."""
            if sql == "ANALYZE":
                raise DatabaseError("Paramètre de recette confidentiel")
            return execute(sql, params, many, context)

        with self.assertLogs("reconciliation.sqlite_statistics", level="ERROR"), connection.execute_wrapper(fail):
            self.assertEqual(maintain_statistics(force=True)["status"], "failed")
        self.assertFalse(connection.connection.in_transaction)

    def test_post_commit_unexpected_failure_is_reported_without_false_rollback(self):
        """Une erreur inattendue du callback est loguée sans divulgation ni échec fictif de l'import committé."""
        with patch("reconciliation.sqlite_statistics.maintain_statistics", side_effect=RuntimeError("SECRET")):
            with self.assertLogs("reconciliation.sqlite_statistics", level="ERROR") as logs:
                with transaction.atomic():
                    Campaign.objects.create(name="Campagne conservée", scope="test")
                    after_campaign_commit()
        self.assertEqual(Campaign.objects.count(), 1)
        self.assertNotIn("SECRET", str(logs.output))


class StatisticsImportTests(TestCase):
    """Intégration à l'import atomique, sans maintenance dans les services de correction."""

    setUp = fixtures.BusinessTests.setUp
    load = fixtures.BusinessTests.load
    inventory = fixtures.BusinessTests.inventory
    entry = fixtures.BusinessTests.entry
    confirm = fixtures.BusinessTests.confirm

    @classmethod
    def setUpClass(cls):
        """Génère une seule fois les sources fictives, sans accès aux données utilisateur."""
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from .test_control_index import synthetic_records
        super().setUpClass()
        cls.folder_sources = TemporaryDirectory()
        cls.records = synthetic_records(Path(cls.folder_sources.name))

    @classmethod
    def tearDownClass(cls):
        """Libère les fichiers synthétiques créés pour cette recette."""
        cls.folder_sources.cleanup()
        super().tearDownClass()

    def test_successful_import_schedules_and_failed_import_does_not(self):
        """Un import validé enregistre sa maintenance après commit ; une erreur ne laisse aucun callback."""
        with patch("reconciliation.sqlite_statistics.maintain_statistics") as service, self.captureOnCommitCallbacks(execute=True):
            self.load()
        service.assert_called_once_with(using="default", after_import=True)
        records = copy.deepcopy(self.records)
        records[-1]["complete"] = 987654
        with patch("reconciliation.sqlite_statistics.maintain_statistics") as service, self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValidationError):
                self.load(records)
        service.assert_not_called()

    def test_business_action_and_refresh_do_not_maintain_statistics(self):
        """Correction, confirmation et lecture des agrégats ne lancent jamais ANALYZE."""
        from .accounting import refresh_project
        from .business import correct_inventory
        from django.urls import reverse
        with patch("reconciliation.sqlite_statistics.maintain_statistics") as service, self.captureOnCommitCallbacks(execute=True):
            self.confirm()
            refresh_project(self.campaign, "P")
            source = self.inventory("C")
            correct_inventory(source.pk, self.user, reason="AMOUNT", amount="6000", expected_version=source.business_version)
            self.client.get(reverse("reconciliation:accounting-list"))
        service.assert_not_called()

    def test_prepare_command_progress_and_statistics_are_separate_from_calculation(self):
        """La commande affiche total et temps, sans modifier les montants ou états des synthèses."""
        before = list(self.campaign.accounting_projects.values_list("project_code", "atlas", "sage", "gap", "state", "data"))
        output = StringIO()
        with patch("reconciliation.sqlite_statistics.maintain_statistics", return_value={
                "status": "skipped", "reason": "statistics_present", "seconds": 0}):
            call_command("prepare_accounting", stdout=output)
        self.assertIn("0/1", output.getvalue())
        self.assertIn("1/1", output.getvalue())
        self.assertIn("projets préparés", output.getvalue())
        self.assertEqual(list(self.campaign.accounting_projects.values_list("project_code", "atlas", "sage", "gap", "state", "data")), before)
