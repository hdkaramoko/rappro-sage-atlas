from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from reconciliation.models import Campaign, CampaignInventory

from .models import Project, ProjectPortfolio


class PortfolioViewsTests(TestCase):
    """Vérifie les opérations et contraintes du portefeuille."""

    def setUp(self) -> None:
        """Crée un compte connecté et un projet de référentiel."""
        self.user = User.objects.create_user("rwanda", password="test")
        self.project = Project.objects.create(code="RW-01", label="Projet Rwanda")
        campaign = Campaign.objects.create(
            name="Inventaire", scope="atlas-complet", is_current=True
        )
        CampaignInventory.objects.create(
            campaign=campaign,
            business_key="RW-01::2026::A",
            project_code="RW-01",
            source_id="A",
            fiscal_year=2026,
        )
        self.client.login(username="rwanda", password="test")

    def test_add_existing_project_and_reject_duplicate(self) -> None:
        """L'ajout administratif reste idempotent pour un projet connu."""
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        url = reverse("projects:portfolio")
        self.client.post(url, {"project_code": " rw-01 "})
        self.client.post(url, {"project_code": "RW-01"})
        self.assertEqual(ProjectPortfolio.objects.count(), 1)

    def test_unknown_project_is_rejected(self) -> None:
        """Un code absent du référentiel ne crée aucun projet ni association."""
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        response = self.client.post(reverse("projects:portfolio"), {"project_code": "ABSENT"})
        self.assertContains(response, "introuvable")
        self.assertEqual(ProjectPortfolio.objects.count(), 0)

    def test_regular_user_cannot_add_own_access(self):
        """Un compte classique ne peut s'attribuer un projet, même connu, par POST direct."""
        response = self.client.post(reverse("projects:portfolio"), {"project_code": "RW-01"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ProjectPortfolio.objects.count(), 0)
        self.assertNotContains(self.client.get(reverse("projects:portfolio")), "Ajouter un projet")

    def test_remove_project_only_deletes_association(self) -> None:
        """Le retrait conserve le projet de référence."""
        entry = ProjectPortfolio.objects.create(user=self.user, project=self.project)
        self.client.post(reverse("projects:portfolio_remove", args=(entry.pk,)))
        self.assertFalse(ProjectPortfolio.objects.exists())
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())

    def test_portfolio_renders_table_and_empty_state(self) -> None:
        response = self.client.get(reverse("projects:portfolio"))
        self.assertContains(response, "Votre portefeuille est vide")
        ProjectPortfolio.objects.create(user=self.user, project=self.project)
        response = self.client.get(reverse("projects:portfolio"))
        self.assertContains(response, "Code projet")
        self.assertContains(response, "Projet Rwanda")
