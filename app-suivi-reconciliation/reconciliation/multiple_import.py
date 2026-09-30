"""Validation du contrat v3 et report collectif des décisions, dans l'import atomique."""

from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Subquery
from reconciliation_contract import ODS, control_identity, digest, money, snapshot

from .models import CampaignInventory, ControlContribution, MultipleControl


def validate_header(header):
    """Refuse un contrat v3 sans politique de calcul explicite ou tolérance valide."""
    if header.get("controls_available") is not True:
        raise ValidationError("Le contrat v3 exige les contrôles de multiples")
    if header.get("sage_amount_currency") != "EUR":
        raise ValidationError("Le contrat exige Charges (Dépenses) en euros")
    if header.get("amount_field") not in (None, "total_project_charges", "total_sage_charges"):
        raise ValidationError("Champ de comparaison Atlas inconnu")
    tolerance = money(header.get("tolerance"))
    if tolerance is None or tolerance < 0:
        raise ValidationError("Tolérance de contrôle invalide")


def import_control(campaign, data, *, inventory=None, previous_by_key=None, persist=True):
    """Recalcule les totaux et vérifie les preuves Atlas contre l'inventaire complet."""
    if not isinstance(data, dict):
        raise ValidationError("Contrôle absent ou mal formé")
    try:
        identity, key = data["identity"], data["key"]
        if key != digest(identity) or identity["strategy"] not in ("STANDARD_BY_DOCUMENT", ODS):
            raise ValueError("Clé de contrôle invalide")
        if not isinstance(identity["parts"][0], str):
            raise ValueError("Projet invalide")
        if campaign.fiscal_year is not None and identity["parts"][1] != campaign.fiscal_year:
            raise ValueError("Contrôle hors exercice")
        expected = (
            inventory.get(key, [])
            if inventory is not None
            else list(
                campaign.inventory.filter(
                    control_key=key, present=True, data__bap_status="Comptabilisé"
                ).values_list("data", flat=True)
            )
        )
        if sorted(expected, key=digest) != sorted(data["atlas"], key=digest):
            raise ValueError("Composition Atlas du contrôle différente de l’inventaire")
        for entry in data["entries"]:
            if control_identity(entry, sage=True) != identity:
                raise ValueError("Écriture SAGE hors du contrôle")
            entry_identity = [
                entry[k]
                for k in (
                    "project_code",
                    "fiscal_year",
                    "document",
                    "journal",
                    "line",
                    "analytic_line",
                )
            ]
            if entry["ref"] != digest(entry_identity):
                raise ValueError("Référence SAGE non stable")
            if entry["identity_complete"] != all(v not in (None, "") for v in entry_identity):
                raise ValueError("Complétude de référence SAGE incohérente")
        computed = snapshot(
            identity,
            expected,
            data["entries"],
            amount_field=campaign.metadata.get("amount_field"),
            tolerance=campaign.metadata["tolerance"],
            reasons=data["reasons"],
        )
        if data != computed:
            raise ValueError("Signature, montants ou diagnostic du contrôle incohérents")
        if persist and campaign.controls.filter(key=key).exists():
            raise ValueError("Contrôle répété")
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise ValidationError(f"Contrôle invalide : {exc}") from exc
    previous = (
        previous_by_key.get(key)
        if previous_by_key is not None
        else MultipleControl.objects.filter(campaign_id=campaign.previous_id, key=key).first()
    )
    control = MultipleControl(
        campaign=campaign,
        key=key,
        project_code=identity["parts"][0],
        strategy=identity["strategy"],
        status=data["status"],
        data=data,
    )
    if previous and previous.data["signature"] == data["signature"]:
        for field in ("state", "comment", "actor_id", "reviewed_at", "origin_id", "version"):
            setattr(control, field, getattr(previous, field))
    if persist:
        control.save()
    return control


def import_control_batch(campaign, payloads):
    """Charge preuves et arbitrages en deux lectures par lot, puis insère en masse."""
    if any(not isinstance(data, dict) or not isinstance(data.get("key"), str) for data in payloads):
        raise ValidationError("Contrôle absent ou clé invalide")
    keys = [data["key"] for data in payloads]
    if len(keys) != len(set(keys)):
        raise ValidationError("Contrôle répété dans le lot")
    inventory = defaultdict(list)
    for key, data in campaign.inventory.filter(
        control_key__in=keys, present=True, data__bap_status="Comptabilisé"
    ).values_list("control_key", "data"):
        inventory[key].append(data)
    previous = (
        {
            row.key: row
            for row in MultipleControl.objects.filter(
                campaign_id=campaign.previous_id, key__in=keys
            )
        }
        if campaign.previous_id
        else {}
    )
    records = [
        import_control(campaign, data, inventory=inventory, previous_by_key=previous, persist=False)
        for data in payloads
    ]
    try:
        with transaction.atomic():
            MultipleControl.objects.bulk_create(records, batch_size=500)
    except IntegrityError as exc:
        raise ValidationError("Contrôle répété dans la campagne") from exc


def finalize_controls(campaign):
    """Reporte les validations par ensemble, sans priorité liée à l'ordre d'import.

    Une modification des preuves invalide d'abord les lignes concernées. Puis
    toutes les reprises candidates sont projetées ensemble : en cas de risque,
    toutes les revendications de la pièce sont à revoir, jamais « la dernière ».
    """
    from .campaigns import decision_record
    from .multiple_review import allocation_plan, context_for, diagnose_plan
    from .review import effective, signature

    uncovered = CampaignInventory.objects.filter(
        campaign=campaign, present=True, data__bap_status="Comptabilisé"
    ).exclude(control_key__in=Subquery(campaign.controls.values("key")))
    if uncovered.exists():
        raise ValidationError("Inventaire Comptabilisé non couvert par les contrôles")
    candidates = []
    for frozen in campaign.reviews.select_related(
        "line__transaction__project",
        "line__group",
        "line__campaign",
        "line__updated_by",
        "line__validation_origin",
    ).iterator(chunk_size=500):
        line = frozen.line
        prior_context = line.multiple_context
        line.multiple_context = context_for(line)
        was_carried = frozen.comparison == "CARRIED"
        line.source_signature = (
            signature(line)
            if frozen.decision.get("current") and prior_context == line.multiple_context
            else ""
        )
        if was_carried and not line.source_signature:
            frozen.comparison = "CHANGED"
            frozen.reasons.append(
                "Contrôle multiple ou références SAGE modifiés / nouvellement disponibles"
            )
        if line.source_signature and line.state == "VALIDATED":
            try:
                plan = allocation_plan(line, effective(line), line.manual_assignment)
                candidates.append((line, frozen, plan))
                for control, amount, refs in plan:
                    ControlContribution.objects.create(
                        control=control, line=line, amount=amount, entries=refs
                    )
            except ValidationError as exc:
                line.source_signature = ""
                frozen.comparison = "CHANGED"
                frozen.reasons.extend(exc.messages)
        line.save(update_fields=["multiple_context", "source_signature"])
        frozen.fingerprint = signature(line)
        frozen.decision = decision_record(line)
        frozen.save(update_fields=["fingerprint", "decision", "comparison", "reasons"])
    risky_keys = set()
    for line, _frozen, plan in candidates:
        diagnostic = diagnose_plan(line, plan, manual=bool(line.manual_assignment))
        previous = line.multiple_diagnostic
        accepted = (
            {d["key"]: set(d.get("shared_entries", [])) for d in previous.get("controls", [])}
            if previous.get("derogation")
            else {}
        )
        for d in diagnostic:
            if d["status"] in ("EXCESS", "UNKNOWN") or not set(
                d.get("shared_entries", [])
            ).issubset(accepted.get(d["key"], set())):
                risky_keys.add(d["key"])
    invalid = [
        (line, frozen)
        for line, frozen, plan in candidates
        if any(control.key in risky_keys for control, _, _ in plan)
    ]
    # Évaluer avant de retirer : sinon le premier refus rendrait le suivant acceptable.
    for line, frozen in invalid:
        ControlContribution.objects.filter(control__campaign=campaign, line=line).delete()
        line.source_signature = ""
        line.save(update_fields=["source_signature"])
        frozen.comparison = "CHANGED"
        frozen.reasons.append(
            "Reprise collective impossible : dépassement, preuve insuffisante ou écriture partagée"
        )
        frozen.decision = decision_record(line)
        frozen.save(update_fields=["comparison", "reasons", "decision"])
