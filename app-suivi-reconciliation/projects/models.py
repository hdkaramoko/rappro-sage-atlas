from django.conf import settings
from django.db import models


class Project(models.Model):
    """Projet connu du référentiel, identifié par un code stable."""

    code = models.CharField("code projet", max_length=50, unique=True, db_index=True)
    label = models.CharField("libellé", max_length=255)
    geography = models.CharField("géographie", max_length=100, blank=True)
    is_active = models.BooleanField("actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs) -> None:
        """Normalise le code projet avant sa sauvegarde."""
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Retourne une représentation lisible du projet."""
        return f"{self.code} — {self.label}"


class ProjectPortfolio(models.Model):
    """Association active entre un compte et un projet visible."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portfolio_entries"
    )
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="portfolio_entries")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "project"), name="unique_user_project")
        ]

    def __str__(self) -> str:
        """Décrit l'association de portefeuille."""
        return f"{self.user} / {self.project.code}"


class PortfolioImport(models.Model):
    """Journal des affectations Excel réussies ; aucun mot de passe dans le fichier."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    filename = models.CharField(max_length=255)
    created_count = models.PositiveIntegerField(default=0)
    existing_count = models.PositiveIntegerField(default=0)
    assignments = models.JSONField(default=list)

    class Meta:
        ordering = ("-created_at", "-pk")
