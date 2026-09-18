from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q, QuerySet

from projects.models import Project


class ReconciliationQuerySet(QuerySet):
    """Centralise le filtrage d'habilitation des rapprochements."""

    def visible_for(self, user):
        """Retourne uniquement les transactions autorisées pour ce compte."""
        if not user.is_authenticated:
            return self.none()
        if user.is_global_admin:
            return self.all()
        return self.filter(project__portfolio_entries__user=user).distinct()


class ReconciliationTransaction(models.Model):
    """État source courant d'une transaction, enrichi d'une correction séparée."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="transactions")
    business_key = models.CharField(max_length=255, unique=True)
    reference = models.CharField("référence", max_length=100)
    label = models.CharField("libellé", max_length=255)
    transaction_date = models.DateField("date de transaction", null=True, blank=True)
    atlas_amount = models.DecimalField(
        "montant Atlas", max_digits=15, decimal_places=2, null=True, blank=True
    )
    sage_amount = models.DecimalField(
        "montant Sage", max_digits=15, decimal_places=2, null=True, blank=True
    )
    atlas_status_source = models.CharField("statut source Atlas", max_length=80, blank=True)
    sage_status = models.CharField("statut Sage", max_length=80, blank=True)
    business_status_override = models.CharField("statut corrigé", max_length=80, blank=True)
    business_comment = models.TextField("commentaire métier", blank=True)
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    corrected_at = models.DateTimeField(null=True, blank=True)
    first_imported_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Nouveau modèle canonique, ajouté sans supprimer les colonnes historiques.
    source_id = models.CharField(
        "identifiant source", max_length=120, null=True, blank=True, db_index=True
    )
    source_project_label = models.CharField("libellé projet source", max_length=255, blank=True)
    fiscal_year = models.PositiveSmallIntegerField("année", null=True, blank=True)
    activity = models.CharField("activité", max_length=255, blank=True)
    budget_line_code = models.CharField("code ligne budgétaire", max_length=100, blank=True)
    budget_line_label = models.CharField("libellé ligne budgétaire", max_length=255, blank=True)
    atlas_label = models.CharField("libellé ATLAS", max_length=500, blank=True)
    atlas_expense_nature = models.CharField("nature de dépense ATLAS", max_length=255, blank=True)
    sage_third_party_code = models.CharField("code tiers SAGE", max_length=100, blank=True)
    third_party_name = models.CharField("nom du tiers", max_length=255, blank=True)
    sage_bap_number = models.CharField("numéro BAP SAGE", max_length=100, blank=True)
    bap_status = models.CharField("statut BAP canonique", max_length=100, blank=True)
    payment_location = models.CharField("lieu de paiement", max_length=255, blank=True)
    payment_method = models.CharField("moyen de paiement", max_length=100, blank=True)
    accounting_date = models.DateField("date comptable canonique", null=True, blank=True)
    sage_document_number = models.CharField(
        "numéro de pièce SAGE canonique", max_length=100, blank=True
    )
    total_project_charges = models.DecimalField(
        "total charges projet", max_digits=18, decimal_places=2, null=True, blank=True
    )
    total_sage_charges = models.DecimalField(
        "total charges SAGE canonique", max_digits=18, decimal_places=2, null=True, blank=True
    )

    suggestion_bap_status = models.CharField("suggestion statut BAP", max_length=100, blank=True)
    suggestion_sage_document_number = models.CharField(
        "suggestion numéro de pièce SAGE", max_length=100, blank=True
    )
    suggestion_accounting_date = models.DateField(
        "suggestion date comptable", null=True, blank=True
    )
    suggestion_total_sage_charges = models.DecimalField(
        "suggestion total charges SAGE", max_digits=18, decimal_places=2, null=True, blank=True
    )

    correction_bap_status = models.CharField("correction statut BAP", max_length=100, blank=True)
    correction_sage_document_number = models.CharField(
        "correction numéro de pièce SAGE", max_length=100, blank=True
    )
    correction_accounting_date = models.DateField(
        "correction date comptable", null=True, blank=True
    )
    correction_total_sage_charges = models.DecimalField(
        "correction total charges SAGE", max_digits=18, decimal_places=2, null=True, blank=True
    )
    correction_active = models.BooleanField("correction active", default=False)
    correction_version = models.PositiveIntegerField("version de correction", default=0)
    objects = ReconciliationQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=("project", "transaction_date")),
            models.Index(fields=("atlas_status_source",)),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("project", "fiscal_year", "source_id"),
                condition=Q(source_id__isnull=False),
                name="unique_source_project_year",
            )
        ]

    @property
    def effective_status(self) -> str:
        """Retourne la correction métier si elle existe, sinon la source Atlas."""
        return self.effective_bap_status

    @property
    def effective_bap_status(self) -> str:
        """Résout le statut BAP selon correction, suggestion puis valeur canonique."""
        if self.correction_active and self.correction_bap_status:
            return self.correction_bap_status
        return self.suggestion_bap_status or self.bap_status or self.atlas_status_source

    @property
    def effective_sage_document_number(self) -> str:
        """Résout le numéro de pièce Sage effectif."""
        if self.correction_active and self.correction_sage_document_number:
            return self.correction_sage_document_number
        return self.suggestion_sage_document_number or self.sage_document_number

    @property
    def effective_accounting_date(self):
        """Résout la date comptable effective."""
        if self.correction_active and self.correction_accounting_date is not None:
            return self.correction_accounting_date
        return self.suggestion_accounting_date or self.accounting_date

    @property
    def effective_total_sage_charges(self):
        """Résout le montant Sage effectif sans transformer une valeur vide en zéro."""
        if self.correction_active and self.correction_total_sage_charges is not None:
            return self.correction_total_sage_charges
        if self.suggestion_total_sage_charges is not None:
            return self.suggestion_total_sage_charges
        if self.total_sage_charges is not None:
            return self.total_sage_charges
        return self.sage_amount

    @property
    def is_corrected(self) -> bool:
        """Indique si une correction métier est actuellement active."""
        return self.correction_active

    @property
    def amount_difference(self) -> Decimal:
        """Calcule l'écart signé entre Atlas et Sage."""
        project_total = self.total_project_charges
        if project_total is None:
            project_total = self.atlas_amount
        sage_total = self.effective_total_sage_charges
        if project_total is None or sage_total is None:
            return Decimal("0")
        return project_total - sage_total

    @property
    def reconciliation_result(self) -> str:
        """Classe l'écart selon les règles simplifiées du MVP."""
        amount_gap = self.amount_difference != Decimal("0")
        canonical_status = self.bap_status or self.atlas_status_source
        status_gap = bool(canonical_status and self.effective_bap_status != canonical_status)
        if amount_gap and status_gap:
            return "ECART_MULTIPLE"
        if amount_gap:
            return "ECART_MONTANT"
        if status_gap:
            return "ECART_STATUT"
        return "OK"

    def __str__(self) -> str:
        """Retourne la clé lisible de la transaction."""
        return self.business_key


class CorrectionHistory(models.Model):
    """Trace immuable de chaque création, modification ou annulation de correction."""

    transaction = models.ForeignKey(
        ReconciliationTransaction, on_delete=models.CASCADE, related_name="correction_history"
    )
    old_value = models.CharField("ancienne valeur", max_length=80, blank=True)
    new_value = models.CharField("nouvelle valeur", max_length=80, blank=True)
    comment = models.TextField("commentaire", blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    changed_at = models.DateTimeField(auto_now_add=True)
    event_type = models.CharField("type d'événement", max_length=20, default="MODIFICATION")
    old_snapshot = models.JSONField("ancien instantané", default=dict, blank=True)
    new_snapshot = models.JSONField("nouvel instantané", default=dict, blank=True)
    version = models.PositiveIntegerField("version", default=1)

    class Meta:
        ordering = ("-changed_at",)


class ReviewGroup(models.Model):
    """Contexte de justification partagé ; la décision demeure individuelle."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    key = models.CharField(max_length=64, unique=True)
    rule = models.CharField(max_length=40)
    match_status = models.CharField(max_length=30)
    sage_total = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    evidence = models.JSONField(default=list)
    version = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class LineReview(models.Model):
    """Instantané métier explicite : KEEP / SET / CLEAR pour chaque champ."""

    transaction = models.OneToOneField(
        ReconciliationTransaction, on_delete=models.PROTECT, related_name="line_review"
    )
    group = models.ForeignKey(ReviewGroup, on_delete=models.PROTECT, related_name="lines")
    state = models.CharField(max_length=16, default="DRAFT")
    values = models.JSONField(default=dict)
    comment = models.TextField(blank=True)
    source_signature = models.CharField(max_length=64, blank=True)
    version = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class ReviewEvent(models.Model):
    """Événement append-only des décisions, valeurs, sources et dérogations."""

    line = models.ForeignKey(LineReview, on_delete=models.PROTECT, related_name="events")
    snapshot = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
