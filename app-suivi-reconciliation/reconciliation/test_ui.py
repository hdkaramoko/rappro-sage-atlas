from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from projects.models import Project, ProjectPortfolio

from .models import LineReview, ReconciliationTransaction, ReviewGroup
from .presentation import money
from .review import signature


class ReviewUITests(TestCase):
    """Vérifie le rendu métier, les permissions et la pagination des écrans de revue."""
    def setUp(self):
        self.user = get_user_model().objects.create_user("ux", password="test")
        self.project = Project.objects.create(code="P", label="Projet")
        ProjectPortfolio.objects.create(user=self.user, project=self.project)
        self.group = ReviewGroup.objects.create(
            project=self.project,
            key="ui",
            rule="MATCH_EXACT",
            match_status="MATCHED",
            sage_total=Decimal("100"),
            evidence=[],
        )
        self.line = self.make_line("A")
        self.client.force_login(self.user)

    def make_line(self, identifier, group=None):
        group = group or self.group
        item = ReconciliationTransaction.objects.create(
            project=group.project,
            business_key=identifier,
            source_id=identifier,
            fiscal_year=2026,
            atlas_label="Fourniture informatique",
            reference=identifier,
            label="Fourniture",
            total_project_charges=Decimal("100"),
            bap_status="Envoyé SAGE",
            sage_document_number="DOC",
            total_sage_charges=100,
            accounting_date="2026-01-01",
            sage_bap_number="BAP-01",
            sage_third_party_code="T-01",
        )
        return LineReview.objects.create(transaction=item, group=group)

    def test_default_uses_status_not_rule(self):
        """Le parcours par défaut inclut les cas manuels après les propositions, sans filtre caché."""
        fuzzy = ReviewGroup.objects.create(
            project=self.project, key="fuzzy", rule="MATCH_FUZZY_REVIEW", match_status="MATCHED"
        )
        unmatched = ReviewGroup.objects.create(
            project=self.project, key="unmatched", rule="UNMATCHED", match_status="UNMATCHED"
        )
        self.make_line("B", fuzzy)
        self.make_line("C", unmatched)
        response = self.client.get(reverse("reconciliation:reviews"))
        self.assertEqual(response.context["page"].paginator.count, 3)
        self.assertNotContains(response, "Brouillon")
        response = self.client.get(reverse("reconciliation:reviews"), {"match_status": ""})
        self.assertEqual(response.context["page"].paginator.count, 3)

    def test_filters_pagination_permissions_and_query_count(self):
        """Vérifie filtres et droits avec le budget métier historique et une lecture de maintenance."""
        for index in range(30):
            self.make_line(str(index))
        other = Project.objects.create(code="SECRET", label="Invisible")
        group = ReviewGroup.objects.create(
            project=other, key="secret", rule="OTHER", match_status="MATCHED"
        )
        hidden = self.make_line("SECRET", group)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                reverse("reconciliation:reviews"),
                {
                    "project": "P",
                    "rule": "MATCH_EXACT",
                    "q": "BAP-01",
                    "page_size": "25",
                    "page": "2",
                    "state": "DRAFT",
                },
            )
        self.assertEqual(len(response.context["page"]), 6)
        self.assertEqual(response.context["page"].paginator.count, 31)
        self.assertNotContains(response, "SECRET")
        self.assertContains(response, "q=BAP-01")
        maintenance_queries = [query for query in queries if 'FROM "maintenance_maintenancestate"' in query["sql"]]
        self.assertEqual(len(maintenance_queries), 1)
        self.assertLessEqual(len(queries) - len(maintenance_queries), 12)
        self.assertEqual(
            self.client.get(reverse("reconciliation:review-detail", args=[hidden.pk])).status_code,
            404,
        )

    def test_detail_context_no_empty_evidence_and_no_attestation(self):
        url = reverse("reconciliation:review-detail", args=[self.line.pk])
        context = reverse("reconciliation:reviews") + "?project=P&page=2"
        response = self.client.get(url, {"return": context})
        self.assertEqual(response.context["return_url"], context)
        self.assertNotContains(response, 'name="acknowledge"')
        self.assertNotContains(response, "<h2>Correspondance SAGE</h2>")
        self.assertContains(response, "data-edit-field")
        response = self.client.get(url, {"return": "https://evil.example/"})
        self.assertEqual(response.context["return_url"], reverse("reconciliation:reviews"))

    def test_explicit_validation_replaces_checkbox_but_keeps_comment(self):
        self.line.refresh_from_db()
        data = {
            "action": "VALIDATED",
            "version": 0,
            "group_version": 0,
            "source": signature(self.line),
            "comment": "",
        }
        for field in ("status", "amount", "document", "date"):
            data[field + "_mode"] = "KEEP"
        data.update(amount_mode="SET", amount="90")
        url = reverse("reconciliation:review-detail", args=[self.line.pk])
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Justifiez")
        self.line.refresh_from_db()
        self.assertEqual(self.line.version, 0)
        data["comment"] = "Répartition décidée après contrôle"
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.line.refresh_from_db()
        self.assertEqual(self.line.state, "VALIDATED")
        self.assertTrue(self.line.events.get().snapshot["derogation"])
        response = self.client.get(url)
        self.assertContains(response, "90,00 €")

    def test_dashboard_login_and_french_formats(self):
        self.assertEqual(money(0), "0,00 €")
        self.assertEqual(money(Decimal("-19735.41")), "-19\u202f735,41 €")
        self.assertEqual(money(None), "—")
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.context["projects_count"], 1)
        self.assertEqual(response.context["pending"], 1)
        self.assertNotContains(response, "Brouillon")
        self.client.logout()
        self.assertRedirects(
            self.client.post(
                reverse("login"),
                {
                    "username": "ux",
                    "password": "test",
                },
            ),
            reverse("dashboard:index"),
        )
