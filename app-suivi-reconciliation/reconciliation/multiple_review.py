"""Affectations explicites et projection par pièce, sous verrou de campagne."""

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from reconciliation_contract import STANDARD, compare, control_identity, digest, entry_from_sage, money
from reconciliation_contract.fuzzy_safety import INDIVIDUAL_RULES

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


def exact_entry(line):
    """Retourne l'unique écriture complète d'une proposition individuelle v3.

    `line` est une LineReview avec transaction, groupe et campagne chargés.
    Vérifie la référence v3, la cardinalité réelle, projet/exercice, montants
    individuels projet/Sage et leurs signes avec tolérance de 0,01 EUR. Les
    doublons ne sont pas dédupliqués pour autoriser une preuve ambiguë.
    Lève ValidationError si non démontrable. Aucun effet de bord SQL/fichier.
    Une affectation EXACT_GROUP est revalidée par sa signature collective et sa
    preuve individuelle ; le total agrégé n'est jamais réservé sur chaque ligne.
    Les règles fuzzy utilisent ces mêmes contrôles individuels ; leur unicité
    bilatérale sur l'inventaire est vérifiée avant toute AUTO par automatic_blockers.
    """
    if line.automatic_assignment.get("kind") == "EXACT_GROUP":
        from .validation_evidence import verified_exact_group_entry
        return verified_exact_group_entry(line)
    raw = [r for candidate in line.group.evidence for r in candidate.get("rows", [])]
    if (not line.campaign_id or line.campaign.metadata.get("schema_version") != 3
            or line.group.rule not in INDIVIDUAL_RULES or line.group.match_status != "MATCHED"
            or len(line.group.evidence) != 1 or len(raw) != 1):
        raise ValidationError("Écriture SAGE exacte non unique ou identité insuffisante")
    candidates = candidates_for(line)
    if len(candidates) != 1:
        raise ValidationError("Écriture SAGE exacte non unique")
    entry = next(iter(candidates.values()))
    amount, total, project = money(entry["amount"]), money(line.group.sage_total), money(line.transaction.total_project_charges)
    if (not entry["identity_complete"] or entry["project_code"] != line.transaction.project.code
            or entry["fiscal_year"] != line.transaction.fiscal_year):
        raise ValidationError("Identité d'écriture SAGE absente ou hors projet/exercice")
    if (amount is None or total is None or project is None
            or abs(total - amount) > Decimal("0.01") or abs(project - amount) > Decimal("0.01")
            or total * amount < 0 or project * amount < 0):
        raise ValidationError("Montants signés incompatibles avec l'écriture SAGE exacte")
    return entry


def compatible_exact_peer(line, contribution):
    """Autorise une pièce partagée entre deux contributions AUTO individuelles distinctes.

    `line` est la proposition automatique en cours ; `contribution` une
    réservation déjà validée. Recontrôle les preuves individuelles, la fraîcheur,
    le montant effectif et la référence réellement réservée. Retourne False
    sur ambiguïté, décision manuelle ou preuve réutilisée, sans modifier la base.
    Cette exemption concerne Exact et fuzzy, jamais une référence réutilisée.
    """
    from .review import effective, is_current
    other = contribution.line
    if other.validation_source != "AUTO" or other.state != "VALIDATED" or not is_current(other):
        return False
    try:
        left, right = exact_entry(line), exact_entry(other)
        resolved = effective(other)
        return (left["ref"] != right["ref"] and contribution.entries == [right["ref"]]
                and contribution.amount == resolved["amount"]
                and money(resolved["amount"]) == (money(other.transaction.total_project_charges)
                    if other.automatic_assignment.get("kind") == "EXACT_GROUP" else money(other.group.sage_total))
                and str(resolved["document"]).strip().upper() == right["document"]
                and str(resolved["date"])[:10] == right["date"])
    except ValidationError:
        return False


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
    if line.automatic_assignment and line.automatic_assignment.get("kind") != "EXACT_GROUP":
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


def allocation_plan(line, resolved, selection, *, verified_entry=None):
    """Décompose une réservation par pièce, sans sommer un total de groupe répété.

    Une sélection manuelle réserve les montants individuels exacts. Sans sélection,
    la correction individuelle réserve le montant saisi sur sa pièce résolue.
    `verified_entry` est exclusivement une preuve Confirmé déjà résolue côté
    serveur. EXACT_GROUP utilise son entrée signée ; les autres parcours restent
    inchangés. Retourne les contrôles/montants/références, sans écriture.
    """
    if verified_entry or line.automatic_assignment.get("kind") == "EXACT_GROUP" and not selection:
        entry = verified_entry or exact_entry(line)
        key = digest(control_identity(entry, sage=True))
        control = line.campaign.controls.filter(key=key, strategy=STANDARD).first()
        if not control or entry not in control.data["entries"]:
            raise ValidationError("Écriture affectée absente des contrôles de campagne")
        return [(control, resolved["amount"], [entry["ref"]])]
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


def diagnose_plan(line, plan, *, manual=False, automatic=False):
    """Calcule les diagnostics des réservations `plan` de `line`, sans écrire.

    Ajoute les contributions des autres lignes aux charges Sage Atlas sources.
    `manual` conserve les alertes des sélections manuelles ; `automatic` permet
    uniquement aux AUTO Exact/fuzzy à écritures distinctes et actuelles de partager
    une pièce. Les références partagées et dépassements restent bloquants.
    Retourne une liste de diagnostics EUR ; aucune dérogation n'est accordée ici.
    """
    diagnostics = []
    for control, amount, refs in plan:
        data = control.data
        others = list(control.contributions.exclude(line=line).select_related(
            "line__transaction__project", "line__group", "line__campaign"))
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
                and not compatible_piece_peer(line, c.line)
                and not (automatic and compatible_exact_peer(line, c)) for c in others),
        )
        diagnostics.append(diagnostic)
    return diagnostics


def apply_projection(line, resolved, selection, *, state, confirmed, comment, automatic=False, verified_entry=None):
    """Contrôle puis remplace les réservations v3 de `line` sous verrou de campagne.

    `resolved` contient le montant individuel EUR et la pièce/date effectifs ;
    `selection` conserve le parcours manuel existant. `automatic=True` revalide
    la preuve unique Exact/fuzzy et autorise les seuls pairs AUTO individuels distincts.
    Les alertes manuelles, références partagées, dépassements et données inconnues
    restent soumis aux contrôles existants (`confirmed` et commentaire).
    Les réservations actives du nouvel inventaire manuel sont exclusives et ne
    peuvent pas être contournées par une ancienne sélection de candidats moteur.
    Retourne le diagnostic ; ValidationError annule les écritures parentes.
    `verified_entry` permet la preuve Confirmé résolue sans candidate écran ; elle
    ne dispense jamais des contrôles de réservation, de partage ou de capacité.
    """
    if not line.campaign_id or line.campaign.metadata.get("schema_version") != 3:
        if selection:
            raise ValidationError("Une campagne v3 est requise pour affecter des écritures")
        return {}
    diagnostics, plan = [], []
    if state == "VALIDATED":
        if automatic and line.group.rule in INDIVIDUAL_RULES:
            entry = exact_entry(line)
            if (str(resolved["document"]).strip().upper() != entry["document"]
                    or str(resolved["date"])[:10] != entry["date"]
                    or money(resolved["amount"]) != (money(line.transaction.total_project_charges)
                        if line.automatic_assignment.get("kind") == "EXACT_GROUP" else money(line.group.sage_total))):
                raise ValidationError("Affectation automatique différente de l'écriture SAGE exacte")
        plan = allocation_plan(line, resolved, selection, verified_entry=verified_entry)
        from .models import ManualAllocation
        refs = {ref for _, _, references in plan for ref in references}
        if refs and ManualAllocation.objects.filter(active=True, entry__campaign=line.campaign, entry__entry_ref__in=refs).exists():
            raise ValidationError("Cette écriture Sage est déjà affectée à un rapprochement manuel d'inventaire.")
        diagnostics = diagnose_plan(line, plan, manual=bool(selection), automatic=automatic)
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
