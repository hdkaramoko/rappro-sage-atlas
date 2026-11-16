"""Non-régression des indicateurs et des lectures allégées du tableau de bord."""

from unittest.mock import patch

from django.db import connection
from django.db.models.query import QuerySet
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from projects.models import Project, ProjectPortfolio
from reconciliation.models import Campaign, CampaignBapHistory, CampaignDepartment, LineReview, ReconciliationTransaction, ReviewGroup
from reconciliation.review import signature
from reconciliation.review_views import visible


class DashboardTests(TestCase):
    """Compare exactement les réponses avant/après sur une base isolée et des sources mixtes."""

    def setUp(self):
        """Crée deux portefeuilles, une campagne volumineuse en métadonnées et des états variés."""
        self.user = User.objects.create_user("dashboard-reader")
        self.admin = User.objects.create_user("dashboard-admin", is_staff=True)
        self.p = Project.objects.create(code="P", label="Projet accessible")
        self.q = Project.objects.create(code="Q", label="Projet hors portefeuille")
        ProjectPortfolio.objects.create(user=self.user, project=self.p)
        metadata = {"department_policy": "project-departments-v1", "pole_policy": "project-poles-v1",
            "bap_history_policy": "bap-history-v1", "project_departments": {
                "P": {"source": "Santé", "consolidated": "SANTE", "pole": "DP Ukraine"}}, "padding": "x" * 280000}
        self.campaign = Campaign.objects.create(name="Campagne active", scope="test", is_current=True, metadata=metadata)
        self.old = Campaign.objects.create(name="Campagne précédente", scope="test", metadata=metadata)
        self.hidden = Campaign.all_objects.create(name="Préparation privée", scope="test", published=False, metadata=metadata)
        CampaignDepartment.objects.create(campaign=self.campaign, project_code="P", source="Santé", consolidated="SANTE",
            pole="DP Ukraine", pole_source="DP Ukraine")
        CampaignBapHistory.objects.create(campaign=self.campaign, project_code="P", bap_sage_number="BAPTEST",
            bap_created_at="2026-01-02T15:30:00", bap_created_by="Auteur test")
        self.group = ReviewGroup.objects.create(project=self.p, key="dashboard-p", rule="MATCH_EXACT",
            match_status="MATCHED", sage_total=100, evidence=[])
        self.other_group = ReviewGroup.objects.create(project=self.q, key="dashboard-q", rule="MATCH_EXACT",
            match_status="MATCHED", sage_total=100, evidence=[])
        self.make_line("draft", version=0)
        self.make_line("validated", state="VALIDATED")
        self.make_line("rejected", state="REJECTED")
        self.make_line("saved-draft", state="DRAFT")
        self.stale = self.make_line("stale", state="VALIDATED")
        ReconciliationTransaction.objects.filter(pk=self.stale.transaction_id).update(atlas_label="Source modifiée")
        self.make_line("outside", state="VALIDATED", group=self.other_group)
        self.make_line("historical", state="VALIDATED", campaign=self.old)
        self.make_line("hidden", state="VALIDATED", campaign=self.hidden)
        self.client.force_login(self.user)

    def make_line(self, identifier, *, state="DRAFT", version=1, group=None, campaign=None):
        """Crée une décision signée et ses preuves, sans utiliser de logique alternative de fraîcheur."""
        group = group or self.group
        source = ReconciliationTransaction.objects.create(project=group.project, business_key=identifier,
            source_id=identifier, fiscal_year=2026, reference=identifier, label="Source", atlas_label="Source",
            bap_status="Envoyé SAGE", total_project_charges=100, total_sage_charges=100,
            sage_bap_number="BAPTEST", sage_third_party_code="T", sage_document_number="FAC1")
        line = LineReview.objects.create(transaction=source, group=group, campaign=campaign or self.campaign,
            validation_origin=self.old, state=state, version=version,
            multiple_context={"contract": 3}, automatic_assignment={"kind": "test", "entries": []})
        line = LineReview.objects.select_related("transaction__project", "group", "inventory_link").get(pk=line.pk)
        if version:
            line.source_signature = signature(line)
            line.save(update_fields=["source_signature"])
        return line

    def indicators(self, response):
        """Extrait uniquement les indicateurs publics et le périmètre de la réponse rendue."""
        return {key: response.context[key] for key in
            ("total", "counts", "projects_count", "review_rate", "pending", "selected_project")}

    def baseline(self, **params):
        """Rejoue le même calcul sans defer, comme avant le correctif, uniquement pendant ce test."""
        with patch.object(QuerySet, "defer", lambda rows, *fields: rows):
            return self.client.get(reverse("dashboard:index"), params)

    def test_mixed_states_exact_baseline_and_scope(self):
        """Les cinq compteurs, le taux, les permissions et la campagne courante restent identiques."""
        for user in (self.user, self.admin):
            self.client.force_login(user)
            for params in ({}, {"project": "P"}):
                with self.subTest(user=user.username, params=params):
                    before = self.indicators(self.baseline(**params))
                    after = self.indicators(self.client.get(reverse("dashboard:index"), params))
                    self.assertEqual(after, before)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(self.indicators(response), {"total": 5, "counts": {
            "draft": 2, "validated": 1, "rejected": 1, "stale": 1}, "projects_count": 1,
            "review_rate": 20, "pending": 3, "selected_project": ""})
        self.assertNotContains(response, "Projet hors portefeuille")
        self.assertEqual(self.client.get(reverse("dashboard:index"), {"project": "Q"}).status_code, 404)

    def test_changed_sources_still_invalidate_decisions(self):
        """La mutation d'un montant ou d'une preuve continue d'être détectée par is_current."""
        before = self.client.get(reverse("dashboard:index")).context["counts"]
        ReconciliationTransaction.objects.filter(source_id="validated").update(total_project_charges=101)
        after = self.client.get(reverse("dashboard:index")).context["counts"]
        self.assertEqual(after["stale"], before["stale"] + 1)
        self.assertEqual(after["validated"], before["validated"] - 1)
        self.assertEqual(self.indicators(self.baseline()), self.indicators(self.client.get(reverse("dashboard:index"))))
        ReviewGroup.objects.filter(pk=self.group.pk).update(evidence=[{"id": "changed", "rows": [{"Numéro pièce": "AUTRE"}]}])
        self.assertEqual(self.client.get(reverse("dashboard:index")).context["counts"]["stale"], 4)

    def test_no_metadata_fetch_or_n_plus_one_and_other_views_unchanged(self):
        """Les deux metadata restent hors SQL, sans lecture différée en boucle ni modification de visible."""
        for i in range(20):
            self.make_line(f"volume-{i}", state="VALIDATED")
        with CaptureQueriesContext(connection) as before_queries:
            before = self.baseline()
        with CaptureQueriesContext(connection) as after_queries:
            after = self.client.get(reverse("dashboard:index"))
        self.assertEqual(self.indicators(after), self.indicators(before))
        self.assertEqual(len(after_queries), len(before_queries))
        self.assertFalse(any('"metadata"' in q["sql"] for q in after_queries))
        self.assertTrue(any('"metadata"' in q["sql"] for q in before_queries))
        self.assertIn('"metadata"', str(visible(self.user).query))
        with CaptureQueriesContext(connection) as empty_queries:
            self.client.get(reverse("dashboard:index"), {"project": "P"})
        self.assertLessEqual(len(empty_queries), len(after_queries) + 1)

    def test_empty_portfolio_and_legacy_without_campaign(self):
        """Les zéros et les lignes historiques hors campagne conservent leur interprétation initiale."""
        outsider = User.objects.create_user("dashboard-empty")
        self.client.force_login(outsider)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual((response.context["total"], response.context["projects_count"], response.context["review_rate"]), (0, 0, 0))
        self.campaign.is_current = False
        self.campaign.save(update_fields=["is_current"])
        line = self.make_line("legacy", state="REJECTED")
        line.campaign = None
        line.save(update_fields=["campaign"])
        self.client.force_login(self.user)
        self.assertEqual(self.indicators(self.baseline()), self.indicators(self.client.get(reverse("dashboard:index"))))

    def test_actual_reimport_marks_changed_decision_stale(self):
        """Un vrai réimport modifié rend la décision obsolète dans les indicateurs courants."""
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from reconciliation.review_import import import_bundle
        from reconciliation.test_campaigns import CampaignTests, atlas, proposal
        with TemporaryDirectory() as folder:
            for number, raw in enumerate((atlas("IMPORTED"), atlas("IMPORTED", **{"Libellé ATLAS": "Source changée"}))):
                records = [{"type": "campaign", "schema_version": 2, "scope": "test", "name": f"Import {number}"},
                    {"type": "inventory", "atlas": raw}, proposal([raw]), {"complete": 1, "inventory_count": 1}]
                path = Path(folder) / "campaign.jsonl"
                path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
                import_bundle(path)
                if number == 0:
                    line = LineReview.objects.select_related("transaction__project", "group").get(transaction__source_id="IMPORTED")
                    CampaignTests.validate(self, line=line)
                response = self.client.get(reverse("dashboard:index"))
                self.assertEqual(response.context["total"], 1)
                self.assertEqual(response.context["counts"]["stale"], number)
                self.assertEqual(response.context["counts"]["validated"], 1-number)
                self.assertEqual(self.indicators(self.baseline()), self.indicators(response))
