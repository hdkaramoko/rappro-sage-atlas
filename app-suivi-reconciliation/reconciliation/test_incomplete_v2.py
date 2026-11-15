"""Recette V2 : projets et lignes distincts, résolution SQL et parcours V1 partagé."""

from decimal import Decimal

from django.db import connection
from django.db.models import Count
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .accounting_models import AccountingProject
from .business import cancel_inventory_link, correct_inventory
from .campaigns import insert_inventory
from .incomplete_accounting import current_manual_link
from .incomplete_views import incomplete_rows
from .models import CampaignAction, CampaignDepartment, CampaignInventory, ManualReconciliation
from .test_incomplete_accounting import IncompleteFixture


class IncompleteV2Tests(IncompleteFixture, TestCase):
    """Réutilise exclusivement les sources fictives V1 et les décisions de ses services."""

    def listing(self, **params):
        """Consulte la sous-vue par projet avec ses filtres, sans mutation métier."""
        response = self.client.get(
            reverse("reconciliation:reviews"),
            {"view": "controls", "channel": "incomplete", **params},
        )
        self.assertEqual(response.status_code, 200)
        return response

    def detail(self, code=None, **params):
        """Consulte le projet autorisé et retourne le tableau paginé de ses seules sources."""
        response = self.client.get(
            reverse(
                "reconciliation:incomplete-project", args=[code or self.source["project_code"]]
            ),
            params,
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_mixed_group_does_not_mix_the_two_analysis_channels(self):
        """Deux Envoyé du même contrôle restent absents des vues Comptabilisés incomplets."""
        sent = [
            {**self.source, "source_id": identifier, "bap_status": "Envoyé SAGE"}
            for identifier in ("ENVOYE-SEPARATE-ONE", "ENVOYE-SEPARATE-TWO")
        ]
        insert_inventory(self.campaign, sent)
        control = self.campaign.global_controls.get(key=self.inventory().control_key)
        finance = self.client.get(
            reverse("reconciliation:global-control-detail", args=[control.pk])
        )
        self.assertEqual(len(finance.context["page"]), 3)
        listing = self.listing()
        self.assertEqual(listing.context["page"][0]["line_count"], 1)
        detail = self.detail()
        self.assertEqual([row.source_id for row in detail.context["page"]], ["1665867"])
        for row in sent:
            self.assertNotContains(detail, row["source_id"])
        self.assertContains(detail, "Rechercher dans Sage")
        self.assertContains(detail, "Charges projet (référence)")
        classic = self.client.get(reverse("reconciliation:reviews"), {"view": "controls"})
        self.assertContains(
            classic,
            reverse("reconciliation:incomplete-project", args=[self.source["project_code"]]),
        )

    def test_active_resolved_cancel_and_source_diagnostic(self):
        """La confirmation quitte la file active ; l'annulation la rouvre sans effacer le masque."""
        self.correction()
        self.confirmation()
        self.assertEqual(self.listing().context["page"].paginator.count, 0)
        history = self.listing(resolution="resolved")
        self.assertEqual(history.context["page"][0]["line_count"], 1)
        self.assertEqual(self.detail(resolution="resolved").context["page"][0].source_id, "1665867")
        self.assertEqual(self.inventory().sage_missing_mask, 7)
        self.assertIsNone(self.inventory().data["total_sage_charges"])
        cancel_inventory_link(
            self.inventory().pk,
            self.user,
            comment="Annulation de recette",
            expected_version=self.inventory().business_version,
        )
        self.assertEqual(self.listing().context["page"][0]["line_count"], 1)
        self.assertEqual(self.listing(resolution="resolved").context["page"].paginator.count, 0)

    def test_sql_resolution_matches_v1_versions_amounts_and_invalidations(self):
        """Le prédicat SQL suit la V1 lors des corrections, confirmations et montants périmés."""

        def check(expected):
            """Compare la décision V1 en mémoire et sa sélection SQL sur cette même source."""
            self.assertEqual(bool(current_manual_link(self.inventory())), expected)
            selected = incomplete_rows(self.user, self.campaign).filter(_incomplete_resolved=True)
            self.assertEqual(selected.exists(), expected)

        check(False)
        self.correction()
        check(False)
        self.confirmation()
        check(True)
        ManualReconciliation.objects.filter(inventory=self.inventory()).update(amount="0")
        check(False)
        self.assertEqual(self.listing().context["page"][0]["line_count"], 1)
        ManualReconciliation.objects.filter(inventory=self.inventory()).update(amount="4213.38")
        check(True)
        correct_inventory(
            self.inventory().pk,
            self.user,
            reason="AMOUNT",
            amount="4213.39",
            comment="Révision du montant",
            expected_version=self.inventory().business_version,
        )
        check(False)
        self.assertEqual(self.listing().context["page"][0]["line_count"], 1)

    def test_multiple_controls_still_count_one_inventory_line(self):
        """Une association sur plusieurs pièces conserve un seul identifiant dans la file."""
        other = self.add_entry("GNF-ZERO", "0")
        self.correction()
        self.confirmation(entry_ids=[self.entry.pk, other.pk])
        history = self.listing(resolution="")
        self.assertEqual(history.context["page"][0]["line_count"], 1)
        self.assertEqual(len(self.detail(resolution="").context["page"]), 1)

    def test_project_filters_pagination_and_reference_provenance(self):
        """Les agrégations par projet partagent filtres Département/Pôle/recherche et pagination."""
        self.campaign.metadata.update(
            department_policy="project-departments-v1", pole_policy="project-poles-v1"
        )
        self.campaign.save(update_fields=["metadata"])
        CampaignDepartment.objects.create(
            campaign=self.campaign,
            project_code=self.source["project_code"],
            consolidated="SANTE",
            pole="DP",
        )
        projects = [Project(code=f"OTHER{i:03}", label=f"Projet recette {i}") for i in range(41)]
        Project.objects.bulk_create(projects)
        ProjectPortfolio.objects.bulk_create(
            [ProjectPortfolio(user=self.user, project=project) for project in projects]
        )
        CampaignDepartment.objects.bulk_create(
            [
                CampaignDepartment(
                    campaign=self.campaign,
                    project_code=project.code,
                    consolidated="AUTRES",
                    pole="Hors DP",
                )
                for project in projects
            ]
        )
        insert_inventory(
            self.campaign, [{**self.source, "project_code": project.code} for project in projects]
        )
        self.assertEqual(len(self.listing().context["page"]), 40)
        self.assertEqual(len(self.listing(page=2).context["page"]), 2)
        for params in (
            {"project": self.source["project_code"]},
            {"department": "SANTE"},
            {"pole": "DP"},
            {"q": "Projet de recette"},
            {"department": "SANTE", "pole": "DP", "q": "19DDU"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.listing(**params).context["page"].paginator.count, 1)

    def test_project_line_pagination_and_contextual_return(self):
        """Les 25 lignes de la page sont seules chargées ; le retour conserve page/filtres/ancre."""
        insert_inventory(
            self.campaign,
            [{**self.source, "source_id": f"LINE-{number:03}"} for number in range(30)],
        )
        listing = self.listing()
        self.assertEqual(listing.context["page"][0]["line_count"], 31)
        detail = self.detail(
            page=2,
            resolution="active",
            **{"return": "/rapprochements/validation/?view=controls&channel=incomplete&page=2"},
        )
        self.assertEqual(len(detail.context["page"]), 6)
        inventory = detail.context["page"][0]
        return_to = inventory.review_return
        self.assertIn("page=2", return_to)
        self.assertTrue(return_to.endswith(f"#incomplete-line-{inventory.pk}"))
        response = self.client.get(
            reverse("reconciliation:inventory-detail", args=[inventory.pk]),
            {"return": return_to, "mode": "search"},
        )
        self.assertEqual(response.context["return_url"], return_to)
        self.assertNotContains(detail, "1665867")

    def test_resolved_line_keeps_a_fallback_anchor_for_the_return(self):
        """Une ligne retirée de la file conserve une cible de retour au début du tableau."""
        identifier = self.inventory().pk
        self.correction()
        self.confirmation()
        response = self.detail(focus=str(identifier))
        self.assertEqual(response.context["page"].paginator.count, 0)
        self.assertContains(response, f'id="incomplete-line-{identifier}"', count=1)

    def test_permissions_direct_post_and_hidden_campaign(self):
        """Les routes refusent les accès hors portefeuille et les POST de consultation."""
        url = reverse("reconciliation:incomplete-project", args=[self.source["project_code"]])
        self.assertEqual(self.client.post(url, {}).status_code, 405)
        outsider = User.objects.create_user("outside-v2")
        self.client.force_login(outsider)
        self.assertEqual(self.listing().context["page"].paginator.count, 0)
        self.assertEqual(self.client.get(url).status_code, 404)
        business_url = reverse("reconciliation:inventory-detail", args=[self.inventory().pk])
        self.assertEqual(
            self.client.post(
                business_url, {"action": "confirm", "entries": [self.entry.pk]}
            ).status_code,
            404,
        )
        admin = User.objects.create_user("admin-v2", is_staff=True)
        self.client.force_login(admin)
        self.assertEqual(self.listing().context["page"].paginator.count, 1)
        self.campaign.published = False
        self.campaign.save(update_fields=["published"])
        self.assertEqual(self.listing().context["page"].paginator.count, 0)

    def test_consultation_does_not_change_financial_results_or_events(self):
        """La séparation UX ne modifie ni cadrage, ni contrôles, ni décisions lors des GET."""
        before = list(
            AccountingProject.objects.values_list("atlas", "sage", "gap", "state", "data")
        )
        controls = list(
            self.campaign.global_controls.values_list("data", "current_data", "current_version")
        )
        with CaptureQueriesContext(connection) as queries:
            self.listing()
            self.detail()
        self.assertLess(len(queries), 35)
        self.assertEqual(
            list(AccountingProject.objects.values_list("atlas", "sage", "gap", "state", "data")),
            before,
        )
        self.assertEqual(
            list(
                self.campaign.global_controls.values_list("data", "current_data", "current_version")
            ),
            controls,
        )
        self.assertFalse(CampaignAction.objects.exists())

    def test_zero_sage_amount_is_not_replaced_by_project_reference(self):
        """Un zéro Sage valide garde sa référence zéro et ne devient pas une charge projet."""
        data = {**self.source, "total_sage_charges": "0"}
        CampaignInventory.objects.filter(pk=self.inventory().pk).update(
            data=data, sage_missing_mask=6
        )
        ManualReconciliation.objects.create(inventory=self.inventory(), active=True, amount=0)
        self.assertTrue(current_manual_link(self.inventory()))
        self.assertEqual(self.listing().context["page"].paginator.count, 0)
        self.assertEqual(
            self.detail(resolution="resolved").context["page"][0].review_reference, Decimal(0)
        )

    def test_invalid_sage_amount_uses_v1_reference_without_false_zero(self):
        """Le bit montant invalide évite un CAST en faux zéro, conformément à la V1."""
        data = {**self.source, "total_sage_charges": "INVALID"}
        CampaignInventory.objects.filter(pk=self.inventory().pk).update(data=data)
        ManualReconciliation.objects.create(
            inventory=self.inventory(), active=True, amount="4213.50"
        )
        self.assertTrue(current_manual_link(self.inventory()))
        self.assertEqual(self.listing().context["page"].paginator.count, 0)

    def test_postgresql_grouped_query_compiles_without_a_server(self):
        """Vérifie la compilation SQL PostgreSQL complète sans prétendre l'exécuter."""
        from django.db.backends.postgresql.base import DatabaseWrapper

        postgres = DatabaseWrapper({"NAME": "compile_only"}, alias="compile_only")
        rows = incomplete_rows(self.user, self.campaign).filter(_incomplete_resolved=False)
        rows = rows.order_by().values("project_code").annotate(n=Count("pk", distinct=True))
        sql, _ = rows.query.get_compiler(connection=postgres).as_sql()
        self.assertIn("COUNT(DISTINCT", sql)
        self.assertIn("GROUP BY", sql)
        self.assertIn("numeric", sql.lower())
        self.assertIsNone(postgres.connection)
