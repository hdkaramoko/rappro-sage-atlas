from django.db import migrations


def backfill_new_fields(apps, schema_editor):
    """Recopie par lots les données historiques vers le modèle enrichi."""
    Transaction = apps.get_model("reconciliation", "ReconciliationTransaction")
    History = apps.get_model("reconciliation", "CorrectionHistory")
    for item in Transaction.objects.select_related("project").iterator(chunk_size=500):
        has_correction = bool(item.business_status_override)
        item.source_id = item.reference
        item.source_project_label = item.project.label
        item.fiscal_year = item.transaction_date.year
        item.atlas_label = item.label
        item.bap_status = item.atlas_status_source
        item.accounting_date = item.transaction_date
        item.total_project_charges = item.atlas_amount
        item.total_sage_charges = item.sage_amount
        item.suggestion_bap_status = item.sage_status
        item.suggestion_total_sage_charges = item.sage_amount
        item.correction_bap_status = item.business_status_override
        item.correction_active = has_correction
        item.correction_version = 1 if has_correction else 0
        item.save(
            update_fields=(
                "source_id", "source_project_label", "fiscal_year", "atlas_label",
                "bap_status", "accounting_date", "total_project_charges",
                "total_sage_charges", "suggestion_bap_status",
                "suggestion_total_sage_charges", "correction_bap_status",
                "correction_active", "correction_version",
            )
        )
    for history in History.objects.select_related("transaction").iterator(chunk_size=500):
        history.old_snapshot = {"bap_status": history.old_value}
        history.new_snapshot = {"bap_status": history.new_value}
        history.event_type = "ANNULATION" if not history.new_value else "MODIFICATION"
        history.version = history.transaction.correction_version or 1
        history.save(update_fields=("old_snapshot", "new_snapshot", "event_type", "version"))


def reverse_backfill(apps, schema_editor):
    """Restaure les colonnes historiques depuis les nouvelles valeurs certaines."""
    Transaction = apps.get_model("reconciliation", "ReconciliationTransaction")
    for item in Transaction.objects.iterator(chunk_size=500):
        if item.source_id:
            item.reference = item.source_id
        if item.atlas_label:
            item.label = item.atlas_label
        if item.accounting_date:
            item.transaction_date = item.accounting_date
        if item.total_project_charges is not None:
            item.atlas_amount = item.total_project_charges
        if item.total_sage_charges is not None:
            item.sage_amount = item.total_sage_charges
        if item.bap_status:
            item.atlas_status_source = item.bap_status
        item.business_status_override = item.correction_bap_status if item.correction_active else ""
        item.save()


class Migration(migrations.Migration):
    """Effectue un backfill déterministe et réversible des données existantes."""

    dependencies = [("reconciliation", "0002_correctionhistory_event_type_and_more")]
    operations = [migrations.RunPython(backfill_new_fields, reverse_backfill)]
