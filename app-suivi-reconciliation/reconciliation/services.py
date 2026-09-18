from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import CorrectionHistory, ReconciliationTransaction


class CorrectionConflictError(RuntimeError):
    """Signale qu'une correction plus récente a été enregistrée entre-temps."""


@dataclass(frozen=True)
class CorrectionSnapshot:
    """Représente les quatre valeurs indissociables d'une correction."""

    bap_status: str = ""
    sage_document_number: str = ""
    accounting_date: date | None = None
    total_sage_charges: Decimal | None = None

    def serializable(self) -> dict:
        """Convertit les dates et décimaux dans un format compatible JSON."""
        values = asdict(self)
        if values["accounting_date"] is not None:
            values["accounting_date"] = values["accounting_date"].isoformat()
        if values["total_sage_charges"] is not None:
            values["total_sage_charges"] = str(values["total_sage_charges"])
        return values


def current_snapshot(item: ReconciliationTransaction) -> CorrectionSnapshot:
    """Capture les quatre valeurs corrigées courantes d'une transaction."""
    return CorrectionSnapshot(
        item.correction_bap_status,
        item.correction_sage_document_number,
        item.correction_accounting_date,
        item.correction_total_sage_charges,
    )


@transaction.atomic
def apply_correction(
    item: ReconciliationTransaction,
    status: str,
    comment: str,
    user,
    sage_document_number: str = "",
    accounting_date: date | None = None,
    total_sage_charges: Decimal | None = None,
    expected_version: int | None = None,
) -> ReconciliationTransaction:
    """Enregistre atomiquement un instantané complet avec contrôle de concurrence."""
    locked = ReconciliationTransaction.objects.select_for_update().get(pk=item.pk)
    if expected_version is not None and locked.correction_version != expected_version:
        raise CorrectionConflictError(
            "Cette transaction a été corrigée entre-temps. Rechargez la page."
        )
    old_snapshot = current_snapshot(locked)
    was_active = locked.correction_active
    locked.correction_bap_status = status.strip()
    locked.correction_sage_document_number = sage_document_number.strip()
    locked.correction_accounting_date = accounting_date
    locked.correction_total_sage_charges = total_sage_charges
    locked.correction_active = True
    locked.correction_version += 1
    locked.business_status_override = locked.correction_bap_status
    locked.business_comment = comment.strip()
    locked.corrected_by = user
    locked.corrected_at = timezone.now()
    locked.save()
    new_snapshot = current_snapshot(locked)
    CorrectionHistory.objects.create(
        transaction=locked,
        old_value=old_snapshot.bap_status,
        new_value=new_snapshot.bap_status,
        old_snapshot=old_snapshot.serializable(),
        new_snapshot=new_snapshot.serializable(),
        event_type="MODIFICATION" if was_active else "CREATION",
        version=locked.correction_version,
        comment=locked.business_comment,
        changed_by=user,
    )
    return locked


@transaction.atomic
def cancel_correction(
    item: ReconciliationTransaction, user, expected_version: int
) -> ReconciliationTransaction:
    """Annule explicitement la correction active sans effacer son historique."""
    locked = ReconciliationTransaction.objects.select_for_update().get(pk=item.pk)
    if locked.correction_version != expected_version:
        raise CorrectionConflictError(
            "Cette transaction a été corrigée entre-temps. Rechargez la page."
        )
    if not locked.correction_active:
        return locked
    old_snapshot = current_snapshot(locked)
    locked.correction_active = False
    locked.correction_version += 1
    locked.correction_bap_status = ""
    locked.correction_sage_document_number = ""
    locked.correction_accounting_date = None
    locked.correction_total_sage_charges = None
    locked.business_status_override = ""
    locked.business_comment = ""
    locked.corrected_by = None
    locked.corrected_at = None
    locked.save()
    CorrectionHistory.objects.create(
        transaction=locked,
        old_value=old_snapshot.bap_status,
        new_value="",
        old_snapshot=old_snapshot.serializable(),
        new_snapshot=CorrectionSnapshot().serializable(),
        event_type="ANNULATION",
        version=locked.correction_version,
        changed_by=user,
    )
    return locked
