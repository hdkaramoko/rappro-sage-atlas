"""Projections de lecture du cadrage, indépendantes des décisions métier."""

from django.db import models


class AccountingProject(models.Model):
    """Synthèse reconstruisible d'un projet/campagne, sans état de validation.

    Montants EUR signés à neuf décimales ; None signifie non calculable.
    data conserve les postes explicatifs et les ventilations par type.
    """

    campaign = models.ForeignKey("Campaign", on_delete=models.CASCADE, related_name="accounting_projects")
    project_code = models.CharField(max_length=100)
    atlas = models.DecimalField(max_digits=28, decimal_places=9, null=True)
    sage = models.DecimalField(max_digits=28, decimal_places=9, null=True)
    gap = models.DecimalField(max_digits=28, decimal_places=2, null=True)
    state = models.CharField(max_length=16, default="INSUFFISANT")
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Une synthèse par projet ; index commun aux deux bases pour filtres et pagination."""

        constraints = [models.UniqueConstraint(fields=("campaign", "project_code"), name="accounting_project_unique")]
        indexes = [models.Index(fields=("campaign", "state", "project_code"), name="accounting_project_idx")]


class AccountingGroup(models.Model):
    """Résultat de cadrage d'un contrôle existant, sans changer son diagnostic.

    Le type MIXTE/NA rend visibles les groupes non ventilables sans appariement
    artificiel. Les détails restent dans la fiche de contrôle liée.
    """

    control = models.OneToOneField("CampaignGlobalControl", on_delete=models.CASCADE, related_name="accounting")
    campaign = models.ForeignKey("Campaign", on_delete=models.CASCADE, related_name="accounting_groups")
    project_code = models.CharField(max_length=100)
    piece_type = models.CharField(max_length=16)
    atlas = models.DecimalField(max_digits=28, decimal_places=9, null=True)
    sage = models.DecimalField(max_digits=28, decimal_places=9, null=True)
    gap = models.DecimalField(max_digits=28, decimal_places=2, null=True)
    state = models.CharField(max_length=16)
    data = models.JSONField(default=dict)

    class Meta:
        """Index de navigation projet/type sans exploration JSON pour la pagination."""

        indexes = [models.Index(fields=("campaign", "project_code", "piece_type", "id"), name="accounting_group_idx")]
