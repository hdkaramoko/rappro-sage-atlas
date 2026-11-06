"""Validation indépendante des propositions et corrections historiques."""

import hashlib
import json
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Campaign, LineReview, ReconciliationTransaction, ReviewEvent, ReviewGroup
from .statuses import BAP_STATUSES

FIELDS = {
    "status": "bap_status",
    "document": "sage_document_number",
    "date": "accounting_date",
    "amount": "total_sage_charges",
}


def source_snapshot(line):
    """Retourne les preuves source et bases métier de fraîcheur de LineReview.

    Conserve les sources immuables et signatures historiques (Lot 2 absent).
    Si une base de correction/lien existe, inclut sa version locale ; les soldes
    des autres décisions ne sont jamais signés. Lecture relationnelle éventuelle,
    aucun écrit. Les montants sont sérialisés en décimales, sans float.
    """
    item = line.transaction

    def stable(value):
        if isinstance(value, Decimal):
            return format(value.quantize(Decimal("0.01")), "f")
        return str(value)

    from reconciliation_contract.atlas_context import ATLAS_CONTEXT, context_number

    from .campaigns import stable_evidence

    return {
        "atlas": {
            **{
                field: context_number(getattr(item, field))
                for field in ATLAS_CONTEXT.values()
                if getattr(item, field) is not None
            },
            **{
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
        **({"multiple_context": line.multiple_context} if line.multiple_context else {}),
        **({"automatic_assignment": line.automatic_assignment} if line.automatic_assignment else {}),
        **({"business_basis": {"adjustment_version": line.adjustment_version,
                               "inventory_link": line.inventory_link_id,
                               "link_version": line.inventory_link.version if line.inventory_link_id else None}}
           if line.adjustment_version or line.inventory_link_id else {}),
    }


def signature(line):
    """Empreinte du contexte source servant au contrôle de fraîcheur et au report."""
    return hashlib.sha256(
        json.dumps(source_snapshot(line), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def is_current(line):
    """Indique si la décision enregistrée porte toujours sur ces preuves sources."""
    return line.source_signature == signature(line)


def effective(line, values=None):
    """Résout KEEP/SET/CLEAR en valeurs individuelles destinées à Atlas."""
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
    manual_refs=None,
    manual_confirm=False,
    multiple_confirm=False,
    _automatic=False,
    _automatic_assignment=None,
    _previous_automatic_assignment=None,
):
    """Enregistre une décision avec permissions, signatures et verrous campagne/groupe.

    `line_id` identifie la ligne, `user` son auteur ; `state`, `values` KEEP/SET/CLEAR
    et `comment` définissent la décision individuelle. Les versions et
    `expected_source` protègent sa fraîcheur. Les paramètres d'affectation et de
    confirmation conservent les avertissements manuels existants. Le parcours
    interne `_automatic` recontrôle les preuves Exact avant réservation et ne
    permet le partage de pièce qu'entre écritures AUTO distinctes et actuelles.
    Retourne LineReview ; ValidationError/PermissionDenied annulent la transaction.
    Persiste décision, contributions, événement et photographie de campagne sans
    modifier les montants sources Atlas/Sage ni les campagnes historiques.
    Le Lot 2 capture les anciennes/nouvelles cibles et recalcule leur état courant
    dans cette même transaction, hors auto-validations de l'import initial.
    """
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
        not _automatic and not ReconciliationTransaction.objects.visible_for(user)
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
    if (values["status"]["mode"] == "SET" or state == "VALIDATED") and resolved[
        "status"
    ] not in BAP_STATUSES:
        raise ValidationError("Le statut BAP doit être Envoyé SAGE ou Comptabilisé.")
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
    from .multiple_review import apply_projection, selected_entries

    selection = (
        line.manual_assignment if manual_refs is None else selected_entries(line, manual_refs)
    )
    if selection and (not manual_confirm or not comment.strip()):
        raise ValidationError(
            "Expliquez votre affectation manuelle dans le commentaire avant validation"
        )
    from .business import prepare_review_change, after_review_change
    business_context = prepare_review_change(line, resolved, state, automatic=_automatic, actor=user)
    previous_assignment = (line.automatic_assignment if _previous_automatic_assignment is None
                           else _previous_automatic_assignment)
    line.automatic_assignment = (_automatic_assignment or {}) if _automatic else {}
    diagnostic = apply_projection(
        line, resolved, selection, state=state, confirmed=multiple_confirm, comment=comment,
        automatic=_automatic,
    )
    before = {"state": line.state, "values": line.values, "version": line.version}
    before["manual_assignment"] = line.manual_assignment
    before["automatic_assignment"] = previous_assignment
    line.validation_source = "AUTO" if _automatic else "MANUAL"
    line.auto_validation_rule = group.rule if _automatic else ""
    line.manual_assignment = selection
    line.multiple_diagnostic = diagnostic
    line.state, line.values, line.comment = state, values, comment.strip()
    if campaign and campaign.metadata.get("schema_version") == 3:
        from .multiple_review import context_for

        line.multiple_context = context_for(line)
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
            "validation_source": line.validation_source,
            "auto_validation_rule": line.auto_validation_rule,
            "state": state,
            "values": values,
            "comment": line.comment,
            "version": line.version,
            "source": source_snapshot(line),
            "warnings": warnings,
            "derogation": bool(warnings and acknowledge),
            "manual_assignment": selection,
            "automatic_assignment": line.automatic_assignment,
            "matching_decision": "MANUAL_MATCH" if selection else "ENGINE_PROPOSAL",
            "multiple_diagnostic": diagnostic,
        },
    )
    from .campaigns import save_decision_snapshot

    save_decision_snapshot(line)
    after_review_change(business_context, line, user)
    return line
