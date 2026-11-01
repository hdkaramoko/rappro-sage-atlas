"""Activation atomique par pièce, sans dérogation ni priorité liée à l'ordre JSONL."""

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from reconciliation_contract import STANDARD, digest, money
from reconciliation_contract.piece_coherence import identifier, validate_check

from .models import ControlContribution, LineReview, ReviewEvent
from .review import FIELDS, decide, is_current, signature
from .campaigns import decision_record


def reject_piece(campaign, frozen_rows, messages):
    """Préserve les décisions humaines et invalide toutes les anciennes AUTO de la pièce."""
    for frozen in frozen_rows:
        line = LineReview.objects.select_related("transaction__project", "group", "campaign").get(pk=frozen.line_id)
        if line.validation_source == "AUTO":
            line.source_signature = ""
            line.save(update_fields=["source_signature"])
            ControlContribution.objects.filter(control__campaign=campaign, line=line).delete()
            ReviewEvent.objects.get_or_create(line=line, campaign=campaign,
                snapshot={"validation_source": "AUTO", "state": "STALE",
                          "reason": "Validation collective impossible", "details": list(messages)})
        frozen.refresh_from_db()
        frozen.reasons = sorted(set(frozen.reasons + list(messages)))
        frozen.decision = decision_record(line)
        frozen.save(update_fields=["reasons", "decision"])


def prepare_piece(campaign, rows, owners):
    if campaign.metadata.get("schema_version") != 3 or campaign.metadata.get("piece_coherence_mode") != "ACTIVE":
        raise ValidationError("Activation collective absente : contrôle manuel requis")
    data = rows[0].group.data.get("piece_coherence")
    if not data or data["status"] != "PIECE_RECONCILED":
        raise ValidationError("Pièce non réconciliée : aucune validation collective")
    validate_check(data)
    members = {frozen.source["source_id"] for frozen in rows}
    if members != {r["source_id"] for r in data["atlas"]} or len(members) != len(rows):
        raise ValidationError("Composition de pièce incomplète ou identités Atlas ambiguës")
    if owners - {r.line_id for r in rows}:
        raise ValidationError("Autre proposition revendiquant la pièce SAGE")
    for frozen in rows:
        line, group_data = frozen.line, frozen.group.data
        if line.version and line.validation_source == "MANUAL":
            raise ValidationError("Décision humaine prioritaire : pièce laissée au contrôle manuel")
        if (group_data.get("rule") != "MATCH_CONFIRMED_ATLAS" or group_data.get("match_status") != "MATCHED"
                or group_data.get("piece_coherence") != data
                or group_data.get("auto_validation") != {"source": "AUTO", "state": "VALIDATED", "rule": "MATCH_CONFIRMED_ATLAS"}
                or line.group.lines.count() != 1 or line.manual_assignment):
            raise ValidationError("Autorisation collective incomplète ou proposition non admissible")
        amount, total = line.transaction.total_project_charges, line.group.sage_total
        if amount is None or total is None or abs(amount - total) > Decimal("0.01"):
            raise ValidationError("Montants Atlas/SAGE incompatibles avec la validation automatique")
    # Les dates ne découpent pas la pièce ; l'affectation individuelle respecte
    # néanmoins les preuves pièce/date exigées par le service métier existant.
    atlas, sage = defaultdict(list), defaultdict(list)
    for row in data["atlas"]:
        atlas[(row["third_party"], row["bap"], row["date"])].append(row)
    for row in data["sage"]:
        sage[(row["third_party"], row["bap"], row["date"])].append(row)
    if atlas.keys() != sage.keys() or any(len(v) != len(sage[k]) for k, v in atlas.items()):
        raise ValidationError("Dates individuelles incompatibles avec les écritures SAGE")
    control_key = digest({"strategy": STANDARD,
                          "parts": [data["project"], rows[0].line.transaction.fiscal_year, data["document"]]})
    controls = {e["ref"]: e for c in campaign.controls.filter(key=control_key)
                for e in c.data["entries"] if e["document"] == data["document"]}
    assignments = {}
    for key, sources in atlas.items():
        left = sorted(sources, key=lambda r: (money(r["amount"]), r["source_id"]))
        right = sorted(sage[key], key=lambda r: (money(r["amount"]), r["ref"]))
        for source, proof in zip(left, right, strict=True):
            if (abs(money(source["amount"]) - money(proof["amount"])) > Decimal("0.01")
                    or money(source["amount"]) * money(proof["amount"]) < 0
                    or proof["ref"] not in controls):
                raise ValidationError("Affectation individuelle non fiable ou écriture SAGE absente")
            assignments[source["source_id"]] = {"piece_signature": data["signature"], "entry": controls[proof["ref"]]}
    return assignments


def validate_piece(campaign, rows, owners):
    from .multiple_review import allocation_plan, diagnose_plan
    assignments = prepare_piece(campaign, rows, owners)
    if all(r.line.state == "VALIDATED" and r.line.validation_source == "AUTO"
           and r.line.automatic_assignment == assignments[r.source["source_id"]]
           and is_current(r.line) for r in rows):
        return
    plans = []
    previous_assignments = {r.line_id: r.line.automatic_assignment for r in rows}
    # Appel dans un savepoint de pièce : réservations, événements et décisions
    # ne sont conservés que si tous les membres passent les mêmes contrôles.
    for frozen in rows:
        line = frozen.line
        line.automatic_assignment = assignments[frozen.source["source_id"]]
        line.save(update_fields=["automatic_assignment"])
        resolved = {"status": line.transaction.bap_status,
                    "document": line.transaction.sage_document_number,
                    "date": line.transaction.accounting_date, "amount": line.group.sage_total}
        plan = allocation_plan(line, resolved, [])
        plans.append((line, plan))
        ControlContribution.objects.filter(control__campaign=campaign, line=line).delete()
        for control, amount, refs in plan:
            ControlContribution.objects.create(control=control, line=line, amount=amount, entries=refs)
    # Toutes les réservations sont présentes avant la première décision.
    for line, plan in plans:
        for d in diagnose_plan(line, plan):
            if d["status"] not in ("BALANCED", "SHORTFALL") or d["shared_entries"] or d["shared_piece"]:
                raise ValidationError("Projection collective incompatible ou écriture déjà consommée")
    for frozen in rows:
        line = LineReview.objects.select_related("transaction__project", "group", "campaign").get(pk=frozen.line_id)
        values = {name: {"mode": "KEEP"} for name in FIELDS}
        values["amount"] = {"mode": "SET", "value": str(line.group.sage_total)}
        decide(line.pk, None, state="VALIDATED", values=values,
               comment="Validation automatique — type de match : MATCH_CONFIRMED_ATLAS ; pièce réconciliée collectivement",
               expected_version=line.version, expected_group_version=line.group.version,
               expected_source=signature(line), _automatic=True,
               _automatic_assignment=assignments[frozen.source["source_id"]],
               _previous_automatic_assignment=previous_assignments[line.pk])
        frozen.fingerprint = signature(LineReview.objects.select_related("transaction__project", "group").get(pk=line.pk))
        frozen.save(update_fields=["fingerprint"])


def apply_collective_validations(campaign, *, progress=None):
    rows = campaign.reviews.select_related("group", "line").iterator(chunk_size=500)
    groups, owners = defaultdict(list), defaultdict(set)
    active = campaign.metadata.get("piece_coherence_mode") == "ACTIVE"
    targets = set()
    for frozen in rows:
        key = (identifier(frozen.source["project_code"]), identifier(frozen.source.get("sage_document_number")))
        groups[key].append(frozen.pk)
        owners[key].add(frozen.line_id)
        for candidate in frozen.group.data.get("evidence", []):
            for proof in candidate.get("rows", []):
                owners[(key[0], identifier(proof.get("Numéro pièce")))].add(frozen.line_id)
        if ((active and frozen.group.data.get("rule") == "MATCH_CONFIRMED_ATLAS")
                or frozen.line.automatic_assignment):
            targets.add(key)
    handled = set()
    for number, key in enumerate(sorted(targets), 1):
        if progress and number % 100 == 0:
            progress("Pièces collectives examinées", number)
        members = list(campaign.reviews.filter(pk__in=groups[key]).select_related(
            "group", "line__transaction__project", "line__group", "line__campaign",
            "line__updated_by", "line__validation_origin",
        ))
        handled.update(r.line_id for r in members)
        try:
            with transaction.atomic():
                validate_piece(campaign, members, owners[key])
        except (ValidationError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            messages = exc.messages if isinstance(exc, ValidationError) else [f"Contrôle collectif invalide : {exc}"]
            reject_piece(campaign, members, messages)
    return handled
