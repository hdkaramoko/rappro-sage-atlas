"""Affectations explicites et projection par pièce, sous verrou de campagne."""

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from reconciliation_contract import STANDARD, compare, control_identity, digest, entry_from_sage

from .models import Campaign, ControlContribution, MultipleControl, MultipleEvent


def candidates_for(line):
    """Expose les vraies écritures candidates v3 ; aucun total de groupe n'est sélectionnable."""
    result = {}
    if not line.campaign_id or line.campaign.metadata.get("schema_version") != 3:
        return result
    for candidate in line.group.evidence:
        for raw in candidate.get("rows", []):
            entry = entry_from_sage(raw)
            if raw.get("entry_ref") != entry["ref"]:
                raise ValidationError("Référence candidate invalide : réimportez la campagne")
            if entry["ref"] in result and result[entry["ref"]] != entry:
                raise ValidationError("Écritures candidates contradictoires")
            result[entry["ref"]] = entry
    return result


def context_for(line):
    """Signe les preuves fixes pertinentes ; ne signe jamais le solde des autres décisions."""
    from .review import effective

    candidates = candidates_for(line)
    keys = {digest(control_identity(e, sage=True)) for e in candidates.values()}
    for document in (line.transaction.sage_document_number, effective(line).get("document")):
        if document:
            keys.add(
                digest(
                    {
                        "strategy": STANDARD,
                        "parts": [
                            line.transaction.project.code,
                            line.transaction.fiscal_year,
                            str(document).strip().upper(),
                        ],
                    }
                )
            )
    controls = list(line.campaign.controls.filter(key__in=keys))
    indexed = {c.key: c for c in controls}
    for entry in candidates.values():
        key = digest(control_identity(entry, sage=True))
        if (
            entry["project_code"] != line.transaction.project.code
            or entry["fiscal_year"] != line.transaction.fiscal_year
        ):
            raise ValidationError("Candidate SAGE hors projet ou exercice")
        if key not in indexed or entry not in indexed[key].data["entries"]:
            raise ValidationError(
                "Candidate absente ou contradictoire avec les preuves de contrôle"
            )
    context = {c.key: c.data["signature"] for c in controls}
    for key in keys - set(context):
        context[key] = "MISSING"
    # Une campagne v3 sans candidat ne doit pas hériter d'une validation v2.
    result = {"contract": 3, "controls": context}
    if line.automatic_assignment:
        from .piece_coherence import campaign_check
        data = campaign_check(line)
        result["piece"] = {"mode": line.campaign.metadata.get("piece_coherence_mode"),
                           "signature": data.get("signature") if data else None}
    return result


def selected_entries(line, references):
    """Revalide côté serveur chaque référence et photographie son contenu courant."""
    available = candidates_for(line)
    if len(references) != len(set(references)):
        raise ValidationError("Une écriture ne peut pas être sélectionnée deux fois")
    if any(ref not in available for ref in references):
        raise ValidationError("Écriture non candidate ou disparue de la photographie")
    return [available[ref] for ref in references]


def allocation_plan(line, resolved, selection):
    """Décompose une réservation par pièce, sans sommer un total de groupe répété.

    Une sélection manuelle réserve les montants individuels exacts. Sans sélection,
    la correction individuelle réserve le montant saisi sur sa pièce résolue.
    """
    if line.automatic_assignment and not selection:
        from .piece_coherence import verified_assignment
        control, entry = verified_assignment(line, resolved)
        return [(control, resolved["amount"], [entry["ref"]])]
    allocations, references = defaultdict(lambda: Decimal(0)), defaultdict(list)
    if selection:
        fresh = selected_entries(line, [e["ref"] for e in selection])
        if fresh != selection:
            raise ValidationError("Les écritures affectées ont changé")
        if any(e["amount"] is None for e in fresh):
            raise ValidationError("Montant SAGE absent : affectation impossible")
        if sum((Decimal(e["amount"]) for e in fresh), Decimal(0)) != resolved["amount"]:
            raise ValidationError(
                "Le montant corrigé doit égaler la somme des écritures sélectionnées"
            )
        if not any(
            e["document"] == str(resolved["document"]).strip().upper()
            and e["date"] == str(resolved["date"])[:10]
            for e in fresh
        ):
            raise ValidationError(
                "La pièce/date principale doit appartenir aux écritures sélectionnées"
            )
        for entry in fresh:
            identity = control_identity(entry, sage=True)
            if identity["strategy"] != STANDARD:
                raise ValidationError(
                    "ODS/ODG : contrôle de l’existant uniquement, sans affectation manuelle"
                )
            key = digest(identity)
            allocations[key] += Decimal(entry["amount"])
            references[key].append(entry["ref"])
    else:
        identity = {
            "strategy": STANDARD,
            "parts": [
                line.transaction.project.code,
                line.transaction.fiscal_year,
                str(resolved["document"]).strip().upper(),
            ],
        }
        key = digest(identity)
        allocations[key] = resolved["amount"]
        references[key] = sorted(
            e["ref"]
            for e in candidates_for(line).values()
            if digest(control_identity(e, sage=True)) == key
        )
    controls = {c.key: c for c in line.campaign.controls.filter(key__in=allocations)}
    if set(controls) != set(allocations):
        raise ValidationError("Pièce SAGE non résolue dans les contrôles : validation impossible")
    plan = []
    for key, amount in sorted(allocations.items()):
        control = controls[key]
        if control.strategy != STANDARD or control.project_code != line.transaction.project.code:
            raise ValidationError("Pièce hors du projet ou stratégie incompatible")
        if control.data["status"] == "UNKNOWN":
            raise ValidationError("Calcul non fiable : " + " ; ".join(control.data["reasons"]))
        if not selection and not any(
            e["date"] == str(resolved["date"])[:10] for e in control.data["entries"]
        ):
            raise ValidationError("Date absente des écritures de la pièce SAGE")
        plan.append((control, amount, references[key]))
    return plan


def diagnose_plan(line, plan, *, manual=False):
    """Ajoute les validations actuelles à la source, remplace la contribution de cette ligne."""
    diagnostics = []
    for control, amount, refs in plan:
        data = control.data
        others = list(control.contributions.exclude(line=line).select_related("line__transaction"))
        contributions = [c.amount for c in others] + [amount]
        source_amounts = [r.get(data["amount_field"]) for r in data["atlas"]]
        diagnostic = compare(
            source_amounts + contributions,
            [e["amount"] for e in data["entries"]],
            reasons=data["reasons"],
            tolerance=data["tolerance"],
        )
        shared = sorted(
            set(refs)
            & {
                ref
                for c in others
                for ref in c.entries
                if manual or c.line.manual_assignment or c.line.group_id != line.group_id
            }
        )
        # Atlas Comptabilisé ne porte pas l'identité analytique ; signaler le
        # partage de pièce sans prétendre identifier l'écriture déjà consommée.
        if manual and refs and data["atlas"]:
            shared = sorted(set(shared + refs))
        from .piece_coherence import compatible_piece_peer
        diagnostic.update(
            key=control.key,
            document=data["identity"]["parts"][-1],
            source_total=data["atlas_total"],
            source_status=data["status"],
            proposed_amount=str(amount),
            other_lines=[c.line.transaction.source_id for c in others],
            source_lines=[r["source_id"] for r in data["atlas"]],
            shared_entries=shared,
            shared_piece=any(c.line.group_id != line.group_id
                and not compatible_piece_peer(line, c.line) for c in others),
        )
        diagnostics.append(diagnostic)
    return diagnostics


def apply_projection(line, resolved, selection, *, state, confirmed, comment):
    """Contrôle puis remplace la réservation ; l'appelant détient le verrou de campagne."""
    if not line.campaign_id or line.campaign.metadata.get("schema_version") != 3:
        if selection:
            raise ValidationError("Une campagne v3 est requise pour affecter des écritures")
        return {}
    diagnostics, plan = [], []
    if state == "VALIDATED":
        plan = allocation_plan(line, resolved, selection)
        diagnostics = diagnose_plan(line, plan, manual=bool(selection))
        unknown = [d for d in diagnostics if d["status"] == "UNKNOWN"]
        if unknown:
            raise ValidationError(
                "Projection impossible : " + " ; ".join(r for d in unknown for r in d["reasons"])
            )
        risk = [
            d
            for d in diagnostics
            if d["status"] == "EXCESS" or d["shared_entries"] or d["shared_piece"]
        ]
        if risk and not (confirmed and comment.strip()):
            details = " ; ".join(
                f"Pièce {d['document']} : Atlas source {d['source_total']} €, "
                f"projeté {d['atlas_total']} €, SAGE {d['sage_total']} € ; "
                f"lignes {', '.join(d['source_lines'] + d['other_lines']) or 'aucune autre'}"
                for d in risk
            )
            raise ValidationError(
                details + ". Justifiez ce risque dans le commentaire avant de valider."
            )
    ControlContribution.objects.filter(control__campaign=line.campaign, line=line).delete()
    for control, amount, refs in plan:
        ControlContribution.objects.create(control=control, line=line, amount=amount, entries=refs)
    return {
        "controls": diagnostics,
        "derogation": bool(
            confirmed
            and any(
                d["status"] == "EXCESS" or d["shared_entries"] or d["shared_piece"]
                for d in diagnostics
            )
        ),
    }


@transaction.atomic
def review_control(pk, user, *, state, comment, version):
    """Arbitre une suspicion avec droits, fraîcheur, verrou commun et événement d'audit."""
    from .campaign_views import projects_for

    entry = MultipleControl.objects.get(pk=pk)
    campaign = Campaign.objects.select_for_update().get(pk=entry.campaign_id)
    control = MultipleControl.objects.select_for_update().get(pk=pk)
    if not user.is_authenticated or (
        not user.is_global_admin
        and not projects_for(user).filter(code=control.project_code).exists()
    ):
        raise PermissionDenied
    if not campaign.is_current or control.version != version:
        raise ValidationError("Campagne close ou revue modifiée : rechargez la page")
    if state not in ("TO_REVIEW", "CONFIRMED", "DISMISSED") or not comment.strip():
        raise ValidationError("Une décision connue et un commentaire sont obligatoires")
    before = {"state": control.state, "comment": control.comment}
    control.state, control.comment = state, comment.strip()
    control.actor, control.reviewed_at, control.origin = user, timezone.now(), campaign
    control.version += 1
    control.save()
    MultipleEvent.objects.create(
        control=control,
        actor=user,
        snapshot={
            "before": before,
            "state": state,
            "comment": control.comment,
            "signature": control.data["signature"],
            "version": control.version,
        },
    )
    return control
