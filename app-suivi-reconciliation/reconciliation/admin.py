"""Consultation administrative des sources et des décisions auditées."""

from django.contrib import admin

from .models import (
    Campaign,
    CampaignGroup,
    CampaignInventory,
    CampaignReview,
    CampaignSageEntry,
    CampaignGlobalControl,
    LineReview,
    ReconciliationTransaction,
    ReviewEvent,
    ReviewGroup,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Expose en consultation les modèles audités, y compris les photographies lot 1."""
    def get_queryset(self, request):
        """Retourne le QuerySet de consultation autorisé pour la requête admin.

        Masque les photographies Atlas/Sage, groupes, décisions et contrôles
        globaux liés à une campagne non publiée. Aucun effet de bord en base.
        """
        rows = super().get_queryset(request)
        if self.model in (CampaignGroup, CampaignInventory, CampaignReview, CampaignSageEntry, CampaignGlobalControl):
            rows = rows.filter(campaign__published=True)
        return rows

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReconciliationTransaction)
class TransactionAdmin(ReadOnlyAdmin):
    list_display = ("source_id", "project", "fiscal_year", "bap_status")
    search_fields = ("source_id", "project__code", "atlas_label")
    fields = (
        "source_id",
        "project",
        "fiscal_year",
        "atlas_label",
        "bap_status",
        "sage_document_number",
        "accounting_date",
        "total_project_charges",
        "total_sage_charges",
    )


admin.site.register(ReviewGroup, ReadOnlyAdmin)
admin.site.register(LineReview, ReadOnlyAdmin)
admin.site.register(ReviewEvent, ReadOnlyAdmin)
for model in (Campaign, CampaignGroup, CampaignInventory, CampaignReview, CampaignSageEntry, CampaignGlobalControl):
    admin.site.register(model, ReadOnlyAdmin)
