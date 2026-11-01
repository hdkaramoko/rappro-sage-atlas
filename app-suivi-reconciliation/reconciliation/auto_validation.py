"""Applique une proposition automatique via les contraintes de la décision manuelle."""
from django.core.exceptions import ValidationError
from django.db import transaction
from decimal import Decimal
from reconciliation_contract.auto_validation import AUTO_VALIDATION_RULES
from .models import ReviewEvent
from .review import FIELDS, decide, is_current, signature
from .campaigns import decision_record


def apply_automatic_validations(campaign, *, progress=None):
    from .collective_validation import apply_collective_validations
    handled = apply_collective_validations(campaign, progress=progress)
    # Recenser toutes les revendications avant de décider : l'ordre du fichier
    # ne doit pas donner la priorité à la première de deux preuves partagées.
    claims = {}
    for frozen in campaign.reviews.select_related("group").iterator(chunk_size=500):
        data = frozen.group.data
        proofs = [r for c in data.get("evidence", []) for r in c.get("rows", [])]
        keys = {(frozen.source["project_code"], str(r.get("Numéro pièce", "")),
                 str(r.get("Date comptable", ""))[:10]) for r in proofs}
        if data.get("rule") == "MATCH_CONFIRMED_ATLAS":
            keys.add((frozen.source["project_code"], frozen.source.get("sage_document_number"),
                      str(frozen.source.get("accounting_date", ""))[:10]))
        for key in keys:
            claims.setdefault(key, set()).add(frozen.line_id)
    shared_lines = {pk for members in claims.values() if len(members) > 1 for pk in members}
    rows = campaign.reviews.select_related(
        "group", "line__transaction__project", "line__group", "line__campaign",
        "line__updated_by", "line__validation_origin",
    )
    for number, frozen in enumerate(rows.iterator(chunk_size=500), 1):
        if progress and number % 500 == 0:
            progress("Validations automatiques examinées", number)
        line = frozen.line
        if line.pk in handled:
            continue
        metadata = frozen.group.data.get("auto_validation")
        # Toute décision humaine, y compris un brouillon enregistré, est prioritaire.
        if line.version and line.validation_source == "MANUAL":
            continue
        if line.validation_source == "AUTO":
            # Une ancienne validation ne peut survivre à la disparition de l'autorisation.
            if not metadata:
                line.source_signature = ""
                line.save(update_fields=["source_signature"])
                frozen.reasons.append("Autorisation automatique absente : contrôle manuel requis")
                frozen.decision = decision_record(line)
                frozen.save(update_fields=["decision", "reasons"])
                ReviewEvent.objects.get_or_create(line=line, campaign=campaign,
                    snapshot={"validation_source": "AUTO", "state": "STALE",
                              "reason": "Autorisation automatique absente"})
                continue
        if not metadata:
            continue
        try:
            if line.pk in shared_lines:
                raise ValidationError("Preuve partagée entre propositions : contrôle manuel requis")
            if metadata != {"source": "AUTO", "rule": line.group.rule, "state": "VALIDATED"}:
                raise ValidationError("Métadonnées automatiques invalides")
            if line.group.match_status != "MATCHED" or line.group.rule not in AUTO_VALIDATION_RULES or line.group.lines.count() != 1:
                raise ValidationError("Proposition automatique non unique ou non fiable")
            amount = line.transaction.total_project_charges
            if amount is None or line.group.sage_total is None or abs(amount-line.group.sage_total) > Decimal("0.01"):
                raise ValidationError("Montants incompatibles avec une validation automatique")
            values = {name: {"mode": "KEEP"} for name in FIELDS}
            if line.group.rule != "MATCH_CONFIRMED_ATLAS":
                proofs = [r for candidate in line.group.evidence for r in candidate.get("rows", [])]
                if len(line.group.evidence) != 1 or not proofs:
                    raise ValidationError("Preuve Sage non unique")
                # Plusieurs écritures peuvent étayer MATCH_AMOUNT ; elles
                # doivent désigner une seule pièce/date pour cette ligne Atlas.
                identities = {(str(r.get("Numéro pièce") or "").strip(),
                               str(r.get("Date comptable") or "")[:10]) for r in proofs}
                if len(identities) != 1 or any(not doc or not date for doc, date in identities):
                    raise ValidationError("Preuves Sage incomplètes ou pièce/date non unique")
                if line.group.rule == "MATCH_EXACT" and len(proofs) != 1:
                    raise ValidationError("Preuve Sage non unique")
                proof = proofs[0]
                values.update(document={"mode": "SET", "value": proof.get("Numéro pièce")}, date={"mode": "SET", "value": str(proof.get("Date comptable", ""))[:10]})
            values["amount"] = {"mode": "SET", "value": str(line.group.sage_total)}
            if line.validation_source == "AUTO" and is_current(line):
                continue
            # Savepoint : un contrôle refus? ne laisse aucune contribution partielle.
            with transaction.atomic():
                decide(line.pk, None, state="VALIDATED", values=values,
                       comment=f"Validation automatique — type de match : {line.group.rule}",
                       expected_version=line.version, expected_group_version=line.group.version,
                       expected_source=signature(line), _automatic=True)
        except ValidationError as exc:
            if line.validation_source == "AUTO":
                line.refresh_from_db()
                line.source_signature = ""
                line.save(update_fields=["source_signature"])
                frozen.decision = decision_record(line)
            frozen.reasons.extend(exc.messages)
            frozen.save(update_fields=["reasons", "decision"])
