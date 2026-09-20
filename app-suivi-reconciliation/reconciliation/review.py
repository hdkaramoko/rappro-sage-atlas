"""Validation indépendante des propositions et corrections historiques."""

import hashlib
import json
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Campaign, LineReview, ReconciliationTransaction, ReviewEvent, ReviewGroup

FIELDS = {
    "status": "bap_status",
    "document": "sage_document_number",
    "date": "accounting_date",
    "amount": "total_sage_charges",
}


def source_snapshot(line):
    item = line.transaction

    def stable(value):
        if isinstance(value, Decimal):
            return format(value.quantize(Decimal("0.01")), "f")
        return str(value)

    from .campaigns import stable_evidence

    return {
        "atlas": {
            field.name: stable(getattr(item, field.name))
            for field in item._meta.fields
            if field.name
            in (
                "source_id",
                "project",
                "fiscal_year",
                "atlas_label",
                "sage_bap_number",
                "sage_third_party_code",
                "total_project_charges",
                *FIELDS.values(),
            )
        },
        "group": {
            "key": line.group.key,
            "rule": line.group.rule,
            "status": line.group.match_status,
            "total": stable(line.group.sage_total),
            "evidence": stable_evidence(line.group.evidence)
            if line.group.context_signature
            else line.group.evidence,
            **({"members": line.group.context_signature} if line.group.context_signature else {}),
        },
    }


def signature(line):
    return hashlib.sha256(
        json.dumps(source_snapshot(line), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def is_current(line):
    return line.source_signature == signature(line)


def effective(line, values=None):
    values = line.values if values is None else values
    result = {}
    for name, source in FIELDS.items():
        entry = values.get(name, {"mode": "KEEP"})
        result[name] = (
            getattr(line.transaction, source)
            if entry["mode"] == "KEEP"
            else None
            if entry["mode"] == "CLEAR"
            else entry.get("value")
        )
    if result["amount"] is not None:
        result["amount"] = Decimal(str(result["amount"]))
    return result


@transaction.atomic
def decide(
    line_id,
    user,
    *,
    state,
    values,
    comment,
    expected_version,
    expected_group_version,
    expected_source,
    acknowledge=False,
):
    """Verrouille le groupe pour éviter deux répartitions concurrentes incompatibles."""
    entry = LineReview.objects.get(pk=line_id)
    # Verrouiller une identité stable : après attente d'un import concurrent,
    # la campagne lue doit être recontrôlée, même si elle vient d'être close.
    campaign = (
        Campaign.objects.select_for_update().get(pk=entry.campaign_id)
        if entry.campaign_id
        else Campaign.objects.select_for_update().filter(is_current=True).first()
    )
    if campaign and (not campaign.is_current or entry.campaign_id != campaign.pk):
        raise ValidationError(
            "Cette ligne appartient à une campagne close. Consultez la campagne courante."
        )
    group = ReviewGroup.objects.select_for_update().get(pk=entry.group_id)
    line = LineReview.objects.select_for_update().select_related("transaction").get(pk=line_id)
    if line.group_id != group.pk:
        raise ValidationError("Le groupe a changé. Rechargez la page.")
    line.group = group
    if (
        not ReconciliationTransaction.objects.visible_for(user)
        .filter(pk=line.transaction_id)
        .exists()
    ):
        raise PermissionDenied
    if (
        line.version != expected_version
        or group.version != expected_group_version
        or signature(line) != expected_source
    ):
        raise ValidationError("La ligne, le groupe ou les sources ont changé. Rechargez la page.")
    if state not in ("DRAFT", "VALIDATED", "REJECTED"):
        raise ValidationError("Décision inconnue.")
    for field in FIELDS:
        entry = values.get(field, {})
        if entry.get("mode") not in ("KEEP", "SET", "CLEAR"):
            raise ValidationError("Mode de correction invalide.")
        if entry["mode"] == "SET" and entry.get("value") in (None, ""):
            raise ValidationError("Une valeur est requise pour remplacer un champ.")
    resolved = effective(line, values)
    if resolved["amount"] is not None and not resolved["amount"].is_finite():
        raise ValidationError("Montant invalide.")
    if resolved["date"]:
        try:
            date.fromisoformat(str(resolved["date"]))
        except ValueError as exc:
            raise ValidationError("Date invalide.") from exc
    warnings = []
    if state == "VALIDATED":
        if any(resolved[k] in (None, "") for k in FIELDS):
            raise ValidationError("Pour valider, renseignez statut, montant, pièce et date.")
        siblings = list(group.lines.select_related("transaction", "group"))
        allocations = [
            resolved
            if other.pk == line.pk
            else {"amount": None}
            if other.state == "REJECTED" or (other.version and not is_current(other))
            else effective(other)
            for other in siblings
        ]
        if group.sage_total is None:
            warnings.append("Aucun total Sage de référence")
        elif any(v["amount"] is None for v in allocations):
            warnings.append("Répartition incomplète")
        elif abs(sum(v["amount"] for v in allocations) - group.sage_total) > Decimal("0.01"):
            warnings.append("Répartition différente du total Sage")
        proofs = [row for candidate in group.evidence for row in candidate.get("rows", [])]
        if not proofs and group.rule == "MATCH_CONFIRMED_ATLAS":
            proofs = [
                {
                    "Numéro pièce": line.transaction.sage_document_number,
                    "Date comptable": str(line.transaction.accounting_date),
                }
            ]
        if proofs and not any(
            str(row.get("Numéro pièce", "")) == str(resolved["document"])
            and str(row.get("Date comptable", ""))[:10] == str(resolved["date"])[:10]
            for row in proofs
        ):
            warnings.append("Pièce/date différente des preuves Sage")
        if group.match_status != "MATCHED":
            warnings.append("Le moteur ne propose pas de correspondance unique")
        if warnings and not (acknowledge and comment.strip()):
            raise ValidationError(
                " ; ".join(warnings)
                + ". Justifiez ces écarts dans le commentaire avant de valider."
            )
    if state == "REJECTED" and not comment.strip():
        raise ValidationError("Un commentaire est obligatoire pour refuser.")
    before = {"state": line.state, "values": line.values, "version": line.version}
    line.state, line.values, line.comment = state, values, comment.strip()
    line.source_signature = signature(line)
    line.version += 1
    line.updated_by = user
    if state == "VALIDATED":
        line.validated_at = timezone.now()
        line.validation_origin = campaign
    else:
        line.validated_at = None
        line.validation_origin = None
    line.save()
    group.version += 1
    group.save(update_fields=["version", "updated_at"])
    ReviewEvent.objects.create(
        line=line,
        actor=user,
        campaign=campaign,
        snapshot={
            "before": before,
            "state": state,
            "values": values,
            "comment": line.comment,
            "version": line.version,
            "source": source_snapshot(line),
            "warnings": warnings,
            "derogation": bool(warnings and acknowledge),
        },
    )
    from .campaigns import save_decision_snapshot

    save_decision_snapshot(line)
    return line
