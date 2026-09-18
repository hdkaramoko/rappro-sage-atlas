from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Project, ProjectPortfolio


class PortfolioViewsTests(TestCase):
    """Vérifie les opérations et contraintes du portefeuille."""

    def setUp(self) -> None:
        """Crée un compte connecté et un projet de référentiel."""
        self.user = User.objects.create_user("rwanda", password="test")
        self.project = Project.objects.create(code="RW-01", label="Projet Rwanda")
        self.client.login(username="rwanda", password="test")

    def test_add_existing_project_and_reject_duplicate(self) -> None:
        """L'ajout est idempotent pour un projet connu."""
        url = reverse("projects:portfolio")
        self.client.post(url, {"project_code": " rw-01 "})
        self.client.post(url, {"project_code": "RW-01"})
        self.assertEqual(ProjectPortfolio.objects.count(), 1)

    def test_unknown_project_is_rejected(self) -> None:
        """Un code absent du référentiel ne crée aucun projet ni association."""
        response = self.client.post(reverse("projects:portfolio"), {"project_code": "ABSENT"})
        self.assertContains(response, "introuvable")
        self.assertEqual(ProjectPortfolio.objects.count(), 0)

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
