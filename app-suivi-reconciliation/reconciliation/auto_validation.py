"""Applique une proposition automatique via les contraintes de la décision manuelle."""
from django.core.exceptions import ValidationError
from django.db import transaction
from decimal import Decimal
from reconciliation_contract.auto_validation import AUTO_VALIDATION_RULES
from reconciliation_contract import compare, control_identity, digest, entry_from_sage
from reconciliation_contract.fuzzy_safety import FUZZY_RULES, INDIVIDUAL_RULES, FuzzySafety
from .models import ControlContribution, LineReview, ReviewEvent
from .review import FIELDS, decide, is_current, signature
from .campaigns import decision_record


def automatic_blockers(campaign):
    """Recense les conflits avant toute AUTO, indépendamment de l'ordre des lignes.

    `campaign` fournit les propositions photographiées et les contrôles v3.
    Retourne {line_id: motif}. Exact v3 est contrôlé par référence d'écriture
    complète et capacité signée agrégée de pièce ; aucun partage partiel d'une
    même écriture n'est autorisé. Les autres règles et anciens contrats gardent
    leur garde pièce/date. Les propositions non autorisées participent néanmoins
    aux revendications pour ne pas masquer un concurrent ambigu. Les décisions
    locales du Lot 2 exigent une nouvelle revue après changement de campagne,
    même si le moteur réémet une autorisation AUTO. Lecture seule.
    Fuzzy requiert en plus les inventaires complets Atlas/Sage et leur unicité
    bilatérale, même si un concurrent n'a pas été retenu par le matching.
    """
    from .multiple_review import exact_entry
    from .business import LOCAL_BUSINESS_REVIEW_REASON
    claims, refs, uncertain, identities = {}, {}, {}, {}
    candidates, amounts, owners = {}, {}, {}
    blocked = {}
    fuzzy_safety = None
    if campaign.reviews.filter(group__data__rule__in=list(FUZZY_RULES)).exists():
        from reconciliation_contract.sage_inventory import CAPABILITY
        if CAPABILITY in campaign.metadata.get("capabilities", []):
            fuzzy_safety = FuzzySafety(campaign.inventory.filter(present=True).values_list("data", flat=True).iterator(chunk_size=500),
                (data["entry"] for data in campaign.sage_inventory.values_list("data", flat=True).iterator(chunk_size=500)))
    rows = campaign.reviews.select_related("group", "line__group", "line__campaign", "line__transaction__project")
    for frozen in rows.iterator(chunk_size=500):
        line, data = frozen.line, frozen.group.data
        proofs = [r for c in data.get("evidence", []) for r in c.get("rows", [])]
        keys = set()
        for raw in proofs:
            key = (frozen.source["project_code"], str(raw.get("Numéro pièce", "")).strip().upper(),
                   str(raw.get("Date comptable", ""))[:10])
            keys.add(key)
            entry = entry_from_sage(raw)
            if entry["identity_complete"] and raw.get("entry_ref") == entry["ref"]:
                refs.setdefault(entry["ref"], set()).add(line.pk)
            else:
                uncertain.setdefault(key, set()).add(line.pk)
        if data.get("rule") == "MATCH_CONFIRMED_ATLAS":
            keys.add((frozen.source["project_code"], str(frozen.source.get("sage_document_number") or "").strip().upper(),
                      str(frozen.source.get("accounting_date", ""))[:10]))
        for key in keys:
            claims.setdefault(key, set()).add(line.pk)
        fuzzy = data.get("rule") in FUZZY_RULES
        exact = campaign.metadata.get("schema_version") == 3 and data.get("rule") in INDIVIDUAL_RULES
        identities[line.pk] = (exact, keys)
        if fuzzy and data.get("auto_validation"):
            try:
                if fuzzy_safety is None or not exact or len(proofs) != 1:
                    raise ValueError("AUTO fuzzy exige une preuve individuelle et les inventaires complets v3")
                fuzzy_safety.verify(frozen.source, exact_entry(line))
            except (ValueError, ValidationError) as exc:
                blocked[line.pk] = str(exc)
        if (not exact or not data.get("auto_validation") or LOCAL_BUSINESS_REVIEW_REASON in frozen.reasons
                or line.version and line.validation_source == "MANUAL"):
            continue
        try:
            entry = exact_entry(line)
            candidates[line.pk] = entry
            key = digest(control_identity(entry, sage=True))
            amounts.setdefault(key, []).append(str(line.transaction.total_project_charges)
                if line.automatic_assignment.get("kind") == "EXACT_GROUP" else str(line.group.sage_total))
            owners.setdefault(key, set()).add(line.pk)
        except ValidationError as exc:
            blocked[line.pk] = " ; ".join(exc.messages)
    for line_id, (exact, keys) in identities.items():
        if not exact and any(len(claims[key]) > 1 for key in keys):
            blocked[line_id] = "Preuve partagée entre propositions : contrôle manuel requis"
        if exact and any(uncertain.get(key, set()) - {line_id} for key in keys):
            blocked[line_id] = "Identité d'écriture SAGE insuffisante chez une proposition concurrente"
    for members in refs.values():
        if len(members) > 1:
            for line_id in members:
                if identities[line_id][0]:
                    blocked[line_id] = "Écriture SAGE réutilisée entre propositions : contrôle manuel requis"
    others = {}
    existing = ControlContribution.objects.filter(control__campaign=campaign, control__key__in=owners).exclude(line_id__in=candidates).select_related(
        "control", "line__group", "line__campaign", "line__transaction__project")
    for contribution in existing.iterator(chunk_size=500):
        if contribution.line.state == "VALIDATED" and is_current(contribution.line):
            others.setdefault(contribution.control.key, []).append(str(contribution.amount))
    controls = {c.key: c for c in campaign.controls.filter(key__in=owners)}
    for key, members in owners.items():
        control = controls.get(key)
        if control is None:
            reason = "Pièce SAGE absente des contrôles : affectation automatique impossible"
        else:
            data = control.data
            diagnosis = compare([r.get(data["amount_field"]) for r in data["atlas"]] + amounts[key] + others.get(key, []),
                                [r["amount"] for r in data["entries"]], reasons=data["reasons"], tolerance=data["tolerance"])
            reason = ("Dépassement collectif du montant disponible de la pièce SAGE" if diagnosis["status"] == "EXCESS"
                      else "Calcul non fiable : " + " ; ".join(diagnosis["reasons"]) if diagnosis["status"] == "UNKNOWN" else "")
        if reason:
            for line_id in members:
                blocked.setdefault(line_id, reason)
    return blocked


def apply_automatic_validations(campaign, *, progress=None):
    """Applique les autorisations moteur aux décisions futures de `campaign`.

    Appelée dans la transaction d'import après les reports, cette fonction
    précontrôle toutes les revendications avant les décisions. Les Confirmé
    utilisent les charges Sage Atlas, les autres règles les charges projet.
    Exact v3 peut partager une pièce uniquement avec des écritures distinctes,
    identifiables et sans dépassement agrégé. Les priorités humaines, signatures,
    événements et savepoints existants sont conservés. Une correction/un lien
    de campagne précédente n'est jamais réactivé automatiquement. `progress` est un rappel
    optionnel. Retourne None ; un refus métier est photographié avec son motif.
    Les fuzzy v3 suivent les contrôles individuels Exact et l'unicité bilatérale
    complète ; un ancien contrat sans inventaire complet ne reçoit aucune nouvelle AUTO fuzzy.
    """
    from .collective_validation import apply_collective_validations
    from .business import LOCAL_BUSINESS_REVIEW_REASON
    from .exact_collective import apply_exact_groups
    handled = apply_exact_groups(campaign, progress=progress)
    handled |= apply_collective_validations(campaign, progress=progress)
    blockers = {key: value for key, value in automatic_blockers(campaign).items() if key not in handled}
    # Retirer toutes les anciennes AUTO refusées avant d'examiner les autres :
    # aucune priorité ne doit résulter de l'ordre des réservations reportées.
    stale = LineReview.objects.filter(pk__in=blockers, validation_source="AUTO", campaign=campaign)
    ControlContribution.objects.filter(control__campaign=campaign, line_id__in=stale.values("pk")).delete()
    stale.update(source_signature="")
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
        if LOCAL_BUSINESS_REVIEW_REASON in frozen.reasons:
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
                ControlContribution.objects.filter(control__campaign=campaign, line=line).delete()
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
            if line.pk in blockers:
                raise ValidationError(blockers[line.pk])
            if metadata != {"source": "AUTO", "rule": line.group.rule, "state": "VALIDATED"}:
                raise ValidationError("Métadonnées automatiques invalides")
            if line.group.match_status != "MATCHED" or line.group.rule not in AUTO_VALIDATION_RULES or line.group.lines.count() != 1:
                raise ValidationError("Proposition automatique non unique ou non fiable")
            amount = (line.transaction.total_sage_charges if line.group.rule == "MATCH_CONFIRMED_ATLAS"
                      else line.transaction.total_project_charges)
            if (amount is None or line.group.sage_total is None or abs(amount-line.group.sage_total) > Decimal("0.01")
                    or line.group.rule == "MATCH_CONFIRMED_ATLAS" and amount * line.group.sage_total < 0):
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
                if line.group.rule in INDIVIDUAL_RULES and len(proofs) != 1:
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
                ControlContribution.objects.filter(control__campaign=campaign, line=line).delete()
                frozen.decision = decision_record(line)
            frozen.reasons.extend(exc.messages)
            frozen.save(update_fields=["reasons", "decision"])
