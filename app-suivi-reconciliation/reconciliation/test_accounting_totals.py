"""Recette des sommes filtrées : précision, droits, pagination et structure du tableau."""

from decimal import Decimal
from time import perf_counter

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .accounting_models import AccountingProject
from .accounting_totals import DecimalTextSum, filtered_totals
from .models import Campaign, CampaignDepartment


class AccountingTotalsTests(TestCase):
    """Utilise des synthèses préparées connues, sans rejouer import ou règles comptables."""

    def setUp(self):
        """Prépare trois projets, deux départements/pôles et un administrateur de test."""
        self.campaign = Campaign.objects.create(
            name="Campagne à ne plus afficher",
            scope="test",
            fiscal_year=2026,
            is_current=True,
            metadata={
                "department_policy": "project-departments-v1",
                "pole_policy": "project-poles-v1",
            },
        )
        self.admin = User.objects.create_user("admin-totals", is_staff=True)
        self.client.force_login(self.admin)
        self.add("P", "100.10", "80.05", "100.10", "-20.05", "NON_CADRE", "A", "DP")
        self.add("Q", "-10.20", "-10.20", "-12.30", "2.10", "NON_CADRE", "B", "Hors DP")
        self.add("R", "0", "0", "0", "0", "CADRE", "A", "DP")

    def add(self, code, initial, atlas, sage, gap, state="CADRE", department="A", pole="DP"):
        """Crée un projet et sa photographie ; retourne la synthèse avec montants connus ou NULL."""
        Project.objects.create(code=code, label=f"Libellé {code}")
        CampaignDepartment.objects.create(
            campaign=self.campaign, project_code=code, consolidated=department, pole=pole
        )
        return AccountingProject.objects.create(
            campaign=self.campaign,
            project_code=code,
            atlas=atlas,
            sage=sage,
            gap=gap,
            state=state,
            data={"prepared": True, "totals": {"initial": initial}},
        )

    def response(self, **parameters):
        """Consulte la vraie vue GET avec ses filtres et retourne sa réponse rendue."""
        response = self.client.get(reverse("reconciliation:accounting-list"), parameters)
        self.assertEqual(response.status_code, 200)
        return response

    def assert_amounts(self, response, expected, count):
        """Compare les sommes décimales et l'effectif, sans arrondir les valeurs attendues."""
        totals = response.context["totals"]
        self.assertEqual(totals["count"], count)
        self.assertEqual(
            tuple(totals[key] for key in ("initial", "atlas", "sage", "gap")),
            tuple(Decimal(value) if value is not None else None for value in expected),
        )

    def test_totals_and_table_structure_without_campaign_banner(self):
        """Les sommes précèdent les projets dans le même tableau, sans bandeau permanent."""
        response = self.response()
        self.assert_amounts(response, ("89.90", "69.85", "87.80", "-17.95"), 3)
        totals = response.context["totals"]
        self.assertEqual(totals["gap"], totals["atlas"] - totals["sage"])
        self.assertNotContains(response, self.campaign.name)
        self.assertEqual(response.context["campaign"].pk, self.campaign.pk)
        self.assertContains(response, 'class="accounting-totals"', count=1)
        self.assertContains(response, '<th scope="row">Total du périmètre filtré')
        html = response.content.decode()
        self.assertLess(html.index('class="accounting-totals"'), html.index(">P</td>"))
        self.assertContains(response, "+", count=None)

    def test_filters_alone_and_combined(self):
        """Projet, département, pôle, état et recherche réduisent exactement les mêmes sommes."""
        cases = [
            ({"project": "P"}, ("100.10", "80.05", "100.10", "-20.05"), 1),
            ({"department": "A"}, ("100.10", "80.05", "100.10", "-20.05"), 2),
            ({"pole": "Hors DP"}, ("-10.20", "-10.20", "-12.30", "2.10"), 1),
            ({"state": "CADRE"}, ("0", "0", "0", "0"), 1),
            ({"q": "Libellé Q"}, ("-10.20", "-10.20", "-12.30", "2.10"), 1),
            (
                {"department": "A", "pole": "DP", "state": "NON_CADRE", "project": "P", "q": "P"},
                ("100.10", "80.05", "100.10", "-20.05"),
                1,
            ),
            (
                {"project": ["P", "Q"], "department": ["A", "B"]},
                ("89.90", "69.85", "87.80", "-17.95"),
                2,
            ),
        ]
        for parameters, expected, count in cases:
            with self.subTest(parameters=parameters):
                self.assert_amounts(self.response(**parameters), expected, count)

    def test_totals_cover_all_pages_with_one_aggregate_query(self):
        """Une seule requête SQL extrait et totalise les scalaires, y compris hors page."""
        for number in range(45):
            self.add(f"EXTRA{number:03}", "0.01", "0.01", "0.01", "0")
        first = self.response()
        with CaptureQueriesContext(connection) as queries:
            second = self.response(page=2)
        self.assertEqual(len(first.context["page"]), 40)
        self.assertEqual(len(second.context["page"]), 8)
        self.assertEqual(first.context["totals"], second.context["totals"])
        self.assert_amounts(second, ("90.35", "70.30", "88.25", "-17.95"), 48)
        sums = [row["sql"] for row in queries if 'AS "sum_initial"' in row["sql"]]
        self.assertEqual(len(sums), 1)
        self.assertNotIn("LIMIT", sums[0])
        self.assertLess(len(queries), 30)

    def test_missing_values_are_not_partial_totals_or_zero(self):
        """NULL JSON, clé absente et colonnes nulles signalent un total incomplet par colonne."""
        for initial in (None, "missing"):
            row = AccountingProject.objects.get(project_code="R")
            row.data = {"prepared": True, "totals": {"initial": initial}}
            if initial == "missing":
                row.data["totals"] = {}
            row.atlas = row.gap = None
            row.save()
            response = self.response()
            self.assert_amounts(response, (None, None, "87.80", None), 3)
            self.assertEqual(response.context["totals"]["initial_missing"], 1)
            self.assertEqual(response.context["totals"]["atlas_missing"], 1)
            self.assertContains(response, "Incomplet : 1 montant absent")

    def test_empty_and_unprepared_scopes(self):
        """Un filtre sans résultat affiche un état vide et aucune ligne de faux totaux nuls."""
        response = self.response(q="projet inexistant")
        self.assert_amounts(response, (None, None, None, None), 0)
        self.assertNotContains(response, 'class="accounting-totals"')
        self.assertContains(response, "Aucun projet pour ces filtres")
        AccountingProject.objects.update(data={"prepared": False})
        self.assertContains(self.response(), "pas encore préparé")

    def test_portfolio_excludes_other_projects_from_totals(self):
        """Les projets hors portefeuille ne contribuent pas, même avec un filtre GET forgé."""
        user = User.objects.create_user("limited-totals")
        ProjectPortfolio.objects.create(user=user, project=Project.objects.get(code="P"))
        self.client.force_login(user)
        self.assert_amounts(self.response(), ("100.10", "80.05", "100.10", "-20.05"), 1)
        self.assert_amounts(self.response(project="Q"), ("100.10", "80.05", "100.10", "-20.05"), 1)
        ProjectPortfolio.objects.all().delete()
        self.assert_amounts(self.response(), (None, None, None, None), 0)

    def test_initial_sum_preserves_large_decimals_and_cancellation(self):
        """Les chaînes JSON à grande précision sont additionnées sans passage par float."""
        values = ("9999999999999999.99", "0.01", "-9999999999999999.98")
        for row, value in zip(
            AccountingProject.objects.order_by("project_code"), values, strict=True
        ):
            row.data["totals"]["initial"] = value
            row.save(update_fields=["data"])
        result = filtered_totals(AccountingProject.objects.all())
        self.assertEqual(result["initial"], Decimal("0.02"))

    def test_thousand_project_json_totals_need_one_query(self):
        """Mesure mille synthèses JSON : une requête, sans transfert des documents complets."""
        AccountingProject.objects.bulk_create(
            [
                AccountingProject(
                    campaign=self.campaign,
                    project_code=f"VOLUME{i:04}",
                    atlas="0.10",
                    sage="0.20",
                    gap="-0.10",
                    data={
                        "prepared": True,
                        "totals": {"initial": "0.30"},
                        "diagnostics": ["x" * 4096],
                    },
                )
                for i in range(1000)
            ]
        )
        rows = AccountingProject.objects.filter(project_code__startswith="VOLUME")
        start = perf_counter()
        with CaptureQueriesContext(connection) as queries:
            totals = filtered_totals(rows)
        self.assertEqual(len(queries), 1)
        self.assertEqual(totals["initial"], Decimal("300.00"))
        self.assertEqual(totals["atlas"], Decimal("100.00"))
        self.assertEqual(totals["sage"], Decimal("200.00"))
        self.assertEqual(totals["gap"], Decimal("-100.00"))
        print(f"BENCH totaux : 1000 projets / JSON 4 Ko, {perf_counter() - start:.3f}s, 1 requête")

    def test_postgresql_numeric_sql_compiles_without_a_server(self):
        """Vérifie le SQL NUMERIC et l'extraction JSON PostgreSQL sans prétendre l'exécuter."""
        from django.db.backends.postgresql.base import DatabaseWrapper
        from django.db.models.fields.json import KeyTextTransform, KeyTransform

        postgres = DatabaseWrapper({"NAME": "compile_only"}, alias="compile_only")
        query = AccountingProject.objects.all().query
        expression = DecimalTextSum(KeyTextTransform("initial", KeyTransform("totals", "data")))
        compiler = query.get_compiler(connection=postgres)
        sql, params = compiler.compile(expression.resolve_expression(query))
        self.assertIn("CAST(SUM(CAST(", sql)
        self.assertIn("AS NUMERIC)) AS TEXT)", sql)
        self.assertIn("#>>", sql)
        self.assertIn(["totals", "initial"], params)
        self.assertIsNone(postgres.connection)
