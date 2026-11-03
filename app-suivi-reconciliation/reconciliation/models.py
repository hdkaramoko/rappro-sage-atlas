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
    rebillable_amount = models.DecimalField(
        "Montant refacturables", max_digits=24, decimal_places=6, null=True, blank=True
    )
    planned_unit_price = models.DecimalField(
        "Prix unitaire prévu", max_digits=24, decimal_places=6, null=True, blank=True
    )
    unit_count = models.DecimalField(
        "Nombre d'unités", max_digits=24, decimal_places=6, null=True, blank=True
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
        ordering = ("-changed_at", "-pk")


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
    context_signature = models.CharField(max_length=64, blank=True)


class LineReview(models.Model):
    """Instantané métier explicite : KEEP / SET / CLEAR pour chaque champ."""

    transaction = models.OneToOneField(
        ReconciliationTransaction, on_delete=models.PROTECT, related_name="line_review"
    )
    group = models.ForeignKey(ReviewGroup, on_delete=models.PROTECT, related_name="lines")
    state = models.CharField(max_length=16, default="DRAFT")
    values = models.JSONField(default=dict)
    manual_assignment = models.JSONField(default=list)
    automatic_assignment = models.JSONField(default=dict)
    multiple_context = models.JSONField(default=dict)
    multiple_diagnostic = models.JSONField(default=dict)
    comment = models.TextField(blank=True)
    validation_source = models.CharField(max_length=6, default="MANUAL", choices=[("MANUAL", "Manuelle"), ("AUTO", "Automatique")])
    auto_validation_rule = models.CharField(max_length=64, blank=True)
    source_signature = models.CharField(max_length=64, blank=True)
    version = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)
    campaign = models.ForeignKey("Campaign", null=True, blank=True, on_delete=models.PROTECT)
    validated_at = models.DateTimeField(null=True, blank=True)
    validation_origin = models.ForeignKey(
        "Campaign",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="origin_validations",
    )


class ReviewEvent(models.Model):
    """Événement append-only des décisions, valeurs, sources et dérogations."""

    line = models.ForeignKey(LineReview, on_delete=models.PROTECT, related_name="events")
    snapshot = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    campaign = models.ForeignKey("Campaign", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        ordering = ("-created_at", "-pk")


class PublishedCampaignManager(models.Manager):
    """Masque les campagnes préparées tant que leur publication n'est pas validée."""

    def get_queryset(self):
        """Les vues métier et sélections de campagne précédente ignorent le staging."""
        return super().get_queryset().filter(published=True)


class Campaign(models.Model):
    """Photographie publiée atomiquement ; les campagnes closes sont en lecture seule."""

    name = models.CharField(max_length=200)
    scope = models.CharField(max_length=200)
    fiscal_year = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict)
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    is_current = models.BooleanField(default=False)
    published = models.BooleanField(default=True)
    objects = PublishedCampaignManager()
    all_objects = models.Manager()
    inventory_complete = models.BooleanField(default=True)
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)
    job = models.OneToOneField(
        "imports_app.MatchingJob", null=True, blank=True, on_delete=models.PROTECT
    )

    class Meta:
        ordering = ("-pk",)
        constraints = [
            models.UniqueConstraint(
                fields=("is_current",), condition=Q(is_current=True), name="one_current_campaign"
            )
        ]

    def __str__(self):
        return self.name


class CampaignInventory(models.Model):
    """Inventaire minimal, comparé en lots ; les absences restent des observations."""

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="inventory")
    business_key = models.CharField(max_length=255)
    project_code = models.CharField(max_length=100, db_index=True)
    source_id = models.CharField(max_length=120)
    fiscal_year = models.PositiveSmallIntegerField()
    data = models.JSONField(default=dict)
    control_key = models.CharField(max_length=64, blank=True, db_index=True)
    ods_scope = models.CharField(max_length=64, blank=True, default="")
    present = models.BooleanField(default=True)
    change = models.CharField(max_length=16, default="NEW")
    differences = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("campaign", "business_key"), name="campaign_inventory_key"
            )
        ]
        indexes = [models.Index(fields=("campaign", "change")),
                   models.Index(fields=("campaign", "ods_scope"), name="atlas_campaign_ods_idx")]


class CampaignGroup(models.Model):
    """Preuves stockées une seule fois par groupe et par campagne."""

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT)
    key = models.CharField(max_length=64)
    data = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("campaign", "key"), name="campaign_group_key")
        ]


class CampaignReview(models.Model):
    """Source et décision photographiées, indépendantes des lignes courantes."""

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="reviews")
    line = models.ForeignKey(LineReview, on_delete=models.PROTECT, related_name="campaign_reviews")
    group = models.ForeignKey(CampaignGroup, on_delete=models.PROTECT, related_name="reviews")
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    source = models.JSONField(default=dict)
    decision = models.JSONField(default=dict)
    comparison = models.CharField(max_length=24, default="NEW")
    reasons = models.JSONField(default=list)
    fingerprint = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("campaign", "line"), name="campaign_review_line")
        ]


class MultipleControl(models.Model):
    """Preuves immuables d'une pièce/groupe et revue indépendante de la suspicion."""

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="controls")
    key = models.CharField(max_length=64)
    project_code = models.CharField(max_length=100, db_index=True)
    strategy = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    data = models.JSONField()
    state = models.CharField(max_length=16, default="TO_REVIEW")
    comment = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    reviewed_at = models.DateTimeField(null=True)
    origin = models.ForeignKey(
        Campaign, null=True, on_delete=models.PROTECT, related_name="control_origins"
    )
    version = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("campaign", "key"), name="campaign_control_key")
        ]
        indexes = [models.Index(fields=("campaign", "project_code", "status"))]


class MultipleEvent(models.Model):
    """Journal append-only des arbitrages de multiples, avec preuves et auteur."""

    control = models.ForeignKey(MultipleControl, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    snapshot = models.JSONField()


class ControlContribution(models.Model):
    """Contribution validée non matérialisée dans Atlas, remplaçable par ligne."""

    control = models.ForeignKey(
        MultipleControl, on_delete=models.PROTECT, related_name="contributions"
    )
    line = models.ForeignKey(LineReview, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    entries = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("control", "line"), name="control_line_contribution")
        ]


class ImportRevision(models.Model):
    """Compteur SQLite transactionnel détectant toute mutation métier pendant la préparation."""

    revision = models.PositiveBigIntegerField(default=0)


class CampaignSageEntry(models.Model):
    """Photographie Sage immuable d'une campagne, indépendante des décisions.

    `record_id` signe le contenu ; `entry_ref` conserve la clé technique v3,
    potentiellement en collision (le contrôle devient alors indéterminé).
    Le montant SQL est en EUR, signé, nullable, à six décimales maximum.
    Les index couvrent la pièce et le groupe composite sans charger l'inventaire.
    """

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="sage_inventory")
    record_id = models.CharField(max_length=64)
    entry_ref = models.CharField(max_length=64)
    project_code = models.CharField(max_length=100)
    fiscal_year = models.PositiveSmallIntegerField(null=True)
    document = models.CharField(max_length=100)
    control_key = models.CharField(max_length=64)
    ods_scope = models.CharField(max_length=64, blank=True, default="")
    amount = models.DecimalField(max_digits=22, decimal_places=6, null=True)
    eligible = models.BooleanField(default=True)
    data = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("campaign", "record_id"), name="campaign_sage_record")]
        indexes = [
            models.Index(fields=("campaign", "project_code", "fiscal_year", "document"), name="sage_campaign_piece_idx"),
            models.Index(fields=("campaign", "control_key"), name="sage_campaign_group_idx"),
            models.Index(fields=("campaign", "entry_ref"), name="sage_campaign_ref_idx"),
            models.Index(fields=("campaign", "ods_scope"), name="sage_campaign_ods_idx"),
        ]


class CampaignGlobalControl(models.Model):
    """Calcul initial immuable ; le service interne retourne les recalculs ciblés.

    `data` distingue le contrôle des Comptabilisé du contrôle consolidé après
    les confirmations applicatives. Aucune décision utilisateur n'est stockée ici.
    """

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="global_controls")
    key = models.CharField(max_length=64)
    project_code = models.CharField(max_length=100)
    state = models.CharField(max_length=16)
    data = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("campaign", "key"), name="campaign_global_key")]
        indexes = [models.Index(fields=("campaign", "project_code", "state"), name="global_campaign_state_idx")]
