import uuid

from django.conf import settings
from django.db import models


class ImportBatch(models.Model):
    """Journal d'une tentative de chargement Excel."""

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "Succès"
        FAILED = "FAILED", "Échec"
        DUPLICATE = "DUPLICATE", "Fichier déjà traité"

    filename = models.CharField("nom du fichier", max_length=255)
    file_hash = models.CharField("empreinte SHA-256", max_length=64, unique=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    imported_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    total_rows = models.PositiveIntegerField(default=0)
    created_rows = models.PositiveIntegerField(default=0)
    updated_rows = models.PositiveIntegerField(default=0)
    unchanged_rows = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("-imported_at",)


class TransactionObservation(models.Model):
    """Relie une transaction aux imports où elle a été observée."""

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="observations")
    transaction = models.ForeignKey(
        "reconciliation.ReconciliationTransaction",
        on_delete=models.CASCADE,
        related_name="observations",
    )
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "transaction"), name="unique_batch_transaction"
            )
        ]


class MatchingJob(models.Model):
    """Import suivi des propositions ; anciens champs conservés pour l'historique."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    state = models.CharField(
        max_length=20,
        default="UPLOADING",
        choices=[
            ("UPLOADING", "Enregistrement des fichiers"),
            ("QUEUED", "En attente de démarrage"),
            ("MATCHING", "Rapprochement en cours"),
            ("IMPORTING", "Chargement des propositions"),
            ("SUCCESS", "Terminé"),
            ("DUPLICATE", "Déjà importé"),
            ("FAILED", "Échec"),
        ],
    )
    active = models.BooleanField(default=True)
    atlas_name = models.CharField(max_length=255)
    sage_name = models.CharField(max_length=255)
    error = models.TextField(blank=True)
    groups_imported = models.PositiveIntegerField(default=0)
    bundle_name = models.CharField(max_length=255, blank=True)
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("active",), condition=models.Q(active=True), name="one_active_matching_job"
            )
        ]
