"""Consultation administrative des sources et des décisions auditées."""

from django.contrib import admin

from .models import LineReview, ReconciliationTransaction, ReviewEvent, ReviewGroup


class ReadOnlyAdmin(admin.ModelAdmin):
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
