"""Contrôle des permissions et de la conservation des données dans l'extraction JSON."""

import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from projects.models import Project, ProjectPortfolio

from .models import Campaign, LineReview, ReconciliationTransaction, ReviewEvent, ReviewGroup


class DatabaseExportTests(TestCase):
    def setUp(self):
        """Prépare des données liées et deux événements afin de vérifier l'historique complet."""
        self.admin = User.objects.create_user("root", is_superuser=True, is_staff=True)
        project = Project.objects.create(code="P", label="Projet témoin")
        ProjectPortfolio.objects.create(user=self.admin, project=project)
        campaign = Campaign.objects.create(name="Campagne", scope="test", is_current=True)
        source = ReconciliationTransaction.objects.create(
            project=project,
            business_key="P::2026::1",
            source_id="1",
            fiscal_year=2026,
            reference="1",
            label="Source",
            total_project_charges="123.45",
        )
        group = ReviewGroup.objects.create(project=project, key="G", rule="MATCH_AMOUNT")
        line = LineReview.objects.create(
            transaction=source,
            group=group,
            campaign=campaign,
            comment="Décision actuelle",
            state="VALIDATED",
            updated_by=self.admin,
        )
        for comment in ("Première décision", "Correction expliquée"):
            ReviewEvent.objects.create(
                line=line, campaign=campaign, actor=self.admin, snapshot={"comment": comment}
            )
        self.url = reverse("reconciliation:database-export")

    def test_only_superuser_can_download_or_see_link(self):
        """Un administrateur staff reste interdit, même en appelant directement l'URL."""
        self.assertEqual(self.client.get(self.url).status_code, 302)
        for staff in (False, True):
            user = User.objects.create_user(f"user-{staff}", is_staff=staff)
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertNotContains(self.client.get(reverse("dashboard:index")), self.url)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("dashboard:index")), self.url)
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_stream_preserves_history_relations_and_excludes_credentials(self):
        """Le JSON conserve les commentaires successifs, clés, dates et décimaux sans secrets."""
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        try:
            content = b"".join(response.streaming_content)
            payload = json.loads(content)
        finally:
            response.close()
        self.assertIn(b'},\n{', content)
        tables = payload["tables"]
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            [r["snapshot"]["comment"] for r in tables["reconciliation.reviewevent"]],
            ["Première décision", "Correction expliquée"],
        )
        event = tables["reconciliation.reviewevent"][0]
        self.assertEqual(event["actor_id"], self.admin.pk)
        self.assertTrue(event["created_at"])
        self.assertEqual(tables["reconciliation.linereview"][0]["comment"], "Décision actuelle")
        self.assertEqual(
            tables["reconciliation.reconciliationtransaction"][0]["total_project_charges"],
            "123.45",
        )
        self.assertEqual(len(tables["projects.projectportfolio"]), 1)
        self.assertNotIn("password", tables["accounts.user"][0])
        self.assertNotIn("sessions.session", tables)
        self.assertIn("reconciliation.multipleevent", tables)
        self.assertIn("imports_app.matchingjob", tables)
        self.assertEqual(ReviewEvent.objects.count(), 2)
