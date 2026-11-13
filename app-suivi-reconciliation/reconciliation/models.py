from decimal import Decimal

from django.conf import settings
from django.db import models
from .accounting_models import AccountingGroup, AccountingProject
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
    """État source courant d'une transaction, enrichi d'une correction séparée.

    Les codes budgétaires admettent 255 caractères et leurs libellés sont des
    textes sans limite métier arbitraire, pour préserver les sources importées.
    """

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
    budget_line_code = models.CharField("code ligne budgétaire", max_length=255, blank=True)
    budget_line_label = models.TextField("libellé ligne budgétaire", blank=True)
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
    """Instantané KEEP/SET/CLEAR et base de correction/lien propre à une campagne.

    Les références Lot 2 ne sont pas des preuves moteur et ne sont jamais
    reportées implicitement dans une nouvelle campagne.
    """

    transaction = models.OneToOneField(
        ReconciliationTransaction, on_delete=models.PROTECT, related_name="line_review"
    )
    group = models.ForeignKey(ReviewGroup, on_delete=models.PROTECT, related_name="lines")
    state = models.CharField(max_length=16, default="DRAFT")
    values = models.JSONField(default=dict)
    manual_assignment = models.JSONField(default=list)
    automatic_assignment = models.JSONField(default=dict)
    inventory_link = models.ForeignKey("ManualReconciliation", null=True, blank=True, on_delete=models.PROTECT)
    adjustment_version = models.PositiveIntegerField(default=0)
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


class CampaignDepartment(models.Model):
    """Rattachement organisationnel immuable d'un projet dans une campagne.

    Une seule association par code et campagne, même sans département connu.
    Aucun lien aux permissions ni au champ geography ; anciens imports sans
    ligne associée interprétés comme Non renseigné. Écrit par lots à l'import.
    """

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="departments")
    project_code = models.CharField(max_length=100)
    source = models.CharField(max_length=255, blank=True)
    consolidated = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("campaign", "project_code"), name="campaign_department_project")]


class CampaignInventory(models.Model):
    """Photographie Atlas ; business_version protège les actions locales concurrentes.

    Les sources data restent immuables ; corrections/liens sont des objets dédiés.
    """

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
    business_version = models.PositiveIntegerField(default=0)

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

    def save(self, *args, **kwargs):
        """Persiste le snapshot puis synchronise ses seuls index de consultation.

        Les opérations sont atomiques ; aucune source ni décision n'est recalculée.
        Les imports en lot suspendent cette synchronisation jusqu'à leur publication.
        Les mises à jour sans changement de décision ne nécessitent aucun indexage.
        """
        from django.db import transaction
        from .control_index import indexing_suspended, sync_review
        with transaction.atomic(using=kwargs.get("using")):
            result = super().save(*args, **kwargs)
            fields = kwargs.get("update_fields")
            if not indexing_suspended.get() and (fields is None or "decision" in fields or "project" in fields):
                sync_review(self)
            return result

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
    Le montant SQL est en EUR, signé, nullable, à neuf décimales maximum.
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
    amount = models.DecimalField(max_digits=25, decimal_places=9, null=True)
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
    """Calcul initial immuable et résultat courant versionné des recalculs ciblés.

    `data` distingue le contrôle des Comptabilisé du contrôle consolidé après
    les confirmations applicatives. Aucune décision utilisateur n'est stockée ici.
    current_state/has_pending sont des projections indexées de lecture ; les
    colonnes nullable évitent une reconstruction complète de table SQLite à l'ajout.
    """

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="global_controls")
    key = models.CharField(max_length=64)
    project_code = models.CharField(max_length=100)
    state = models.CharField(max_length=16)
    data = models.JSONField()
    current_data = models.JSONField(null=True, blank=True)
    current_updated_at = models.DateTimeField(null=True, blank=True)
    current_version = models.PositiveIntegerField(default=0)
    current_state = models.CharField(max_length=16, null=True, editable=False)
    has_pending = models.BooleanField(null=True, editable=False)

    def save(self, *args, **kwargs):
        """Actualise l'état indexé depuis le résultat déjà calculé, sans lancer le moteur.

        Les colonnes techniques restent cohérentes lors des recalculs ciblés et des
        sauvegardes directes. Les créations par lots fournissent explicitement ces
        valeurs. Le JSON initial et sa signature restent inchangés.
        """
        self.current_state = (self.current_data or self.data).get("state", "INDETERMINE")
        if self.has_pending is None:
            self.has_pending = False
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"current_state", "has_pending"}
        return super().save(*args, **kwargs)

    class Meta:
        """Identité unique et index couvrants des filtres et de la pagination par projet."""
        constraints = [models.UniqueConstraint(fields=("campaign", "key"), name="campaign_global_key")]
        indexes = [models.Index(fields=("campaign", "project_code", "state"), name="global_campaign_state_idx"),
                   models.Index(fields=("campaign", "project_code", "current_state", "has_pending"), name="global_current_filter_idx"),
                   models.Index(fields=("campaign", "project_code", "id"), name="global_current_page_idx")]


class ReviewControlContext(models.Model):
    """Projection technique des clés de contexte d'une décision photographiée.

    Aucun registre d'affectation : une relation exprime seulement qu'une proposition
    concerne un contrôle. Supprimable/reconstructible depuis CampaignReview.decision.
    Permet d'actualiser les alertes sans rechercher chaque clé dans tous les JSON.
    """
    review = models.ForeignKey(CampaignReview, on_delete=models.CASCADE, related_name="control_contexts")
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="review_control_contexts")
    project_code = models.CharField(max_length=100)
    key = models.CharField(max_length=64)
    pending = models.BooleanField()

    class Meta:
        """Un contexte unique par revue/clé ; recherche ciblée par campagne/projet/clé."""
        constraints = [models.UniqueConstraint(fields=("review", "key"), name="review_control_context_key")]
        indexes = [models.Index(fields=("campaign", "project_code", "key", "pending"), name="review_control_pending_idx")]


class AtlasAdjustment(models.Model):
    """Correction locale à une ligne de campagne, sans modifier la photographie source.

    AMOUNT retient un montant EUR à deux décimales ; DUPLICATE exclut la ligne
    du calcul sans la supprimer. Les annulations conservent l'objet et l'audit.
    """

    class Reason(models.TextChoices):
        """Motifs métier centralisés des corrections financières du Lot 2."""
        AMOUNT = "AMOUNT", "Montant erroné"
        DUPLICATE = "DUPLICATE", "Doublon"

    inventory = models.OneToOneField(CampaignInventory, on_delete=models.PROTECT, related_name="adjustment")
    reason = models.CharField(max_length=16, choices=Reason.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    comment = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class ManualReconciliation(models.Model):
    """Confirmation manuelle issue de l'inventaire, distincte de toute preuve moteur.

    Liée à une seule source de campagne ; toute modification de correction après
    confirmation rend le lien à revoir jusqu'à une nouvelle confirmation explicite.
    """

    inventory = models.OneToOneField(CampaignInventory, on_delete=models.PROTECT, related_name="inventory_match")
    active = models.BooleanField(default=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    adjustment_version = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    comment = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class ManualAllocation(models.Model):
    """Réservation d'une écriture Sage entière ; annulation logique et unicité active.

    Les montants EUR conservent les neuf décimales sources. Les références en
    collision sont refusées par le service avant l'insertion sous verrou campagne.
    """

    link = models.ForeignKey(ManualReconciliation, on_delete=models.PROTECT, related_name="allocations")
    entry = models.ForeignKey(CampaignSageEntry, on_delete=models.PROTECT, related_name="manual_allocations")
    amount = models.DecimalField(max_digits=25, decimal_places=9)
    active = models.BooleanField(default=True)

    class Meta:
        """Une écriture entière ne peut être réservée qu'une fois à l'état actif."""
        constraints = [models.UniqueConstraint(fields=("entry",), condition=Q(active=True), name="one_active_manual_entry")]


class CampaignAction(models.Model):
    """Audit append-only d'une action Lot 2 et clé d'idempotence de sa soumission.

    Les snapshots avant/après incluent les contrôles concernés ; aucun événement
    passé n'est supprimé lors d'une annulation. request_hash interdit de réemployer
    un identifiant réseau avec une autre action ou d'autres paramètres.
    """

    inventory = models.ForeignKey(CampaignInventory, on_delete=models.PROTECT, related_name="business_events")
    request_id = models.UUIDField(unique=True)
    request_hash = models.CharField(max_length=64)
    kind = models.CharField(max_length=24)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Présente l'audit dans l'ordre inverse des actions sans écraser l'historique."""
        ordering = ("-pk",)
