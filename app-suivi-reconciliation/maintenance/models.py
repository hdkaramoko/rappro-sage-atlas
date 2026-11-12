"""État singleton et historique durable de la maintenance applicative."""

from django.conf import settings
from django.db import models


class MaintenanceState(models.Model):
    """Conserve l'état partagé ; seule la ligne de clé 1 peut exister."""

    class State(models.TextChoices):
        """Énumère les trois états exclusifs, sans activation liée à une date."""

        NORMAL = "NORMAL", "Normal"
        SCHEDULED = "SCHEDULED", "Programmée / avertissement"
        ACTIVE = "ACTIVE", "Active"

    state = models.CharField("état", max_length=12, choices=State.choices, default=State.NORMAL)
    message = models.CharField("message", max_length=2000, blank=True)
    planned_at = models.DateTimeField("début prévisionnel", null=True, blank=True)
    updated_at = models.DateTimeField("dernière modification", null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="maintenance_changes")
    version = models.PositiveIntegerField(default=0)

    class Meta:
        """Interdit les configurations multiples et nomme le panneau d'administration."""

        verbose_name = "maintenance de l’application"
        verbose_name_plural = "maintenance de l’application"
        constraints = [models.CheckConstraint(condition=models.Q(pk=1), name="maintenance_singleton")]


class MaintenanceEvent(models.Model):
    """Photographie chaque changement avec son acteur, conservé même après suppression du compte."""

    previous_state = models.CharField(max_length=12)
    next_state = models.CharField(max_length=12)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    actor_label = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)
    message = models.CharField(max_length=2000, blank=True)
    planned_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True)
