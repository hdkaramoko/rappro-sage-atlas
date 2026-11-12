"""Reprise explicite et auditée des actions métier sur des sources inchangées."""

from collections import defaultdict
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from reconciliation_contract import digest

from .business import (adjustment_version, confirm_inventory_link, correct_inventory,
                       manual_link_snapshot)
from .models import CampaignAction, CampaignReview


def sage_identity(entry):
    """Signe le contenu métier Sage, sans empreinte de fichier ni référence dérivée.

    Inclut montants, devise, tiers, libellés, pièce, date, journal et numéros de
    ligne ainsi que les attributs source. Une collision interdit toute reprise.
    Lecture pure ; aucune normalisation susceptible de masquer un changement.
    """
    return digest({"entry": {k: v for k, v in entry.data["entry"].items() if k != "ref"},
                   "attributes": entry.data.get("attributes", {}), "eligible": entry.eligible})


def duplicate_witnesses(inventory):
    """Retourne les témoins strictement identiques d'un doublon dans sa campagne.

    source_id et le BAP de présentation sont écartés ; identité projet/exercice, contenu et présence
    doivent coïncider. Sans témoin conservé, l'exclusion exige confirmation.
    L'ajout du champ d'affichage ne modifie pas la définition historique du doublon.
    """
    content = {k: v for k, v in inventory.data.items() if k not in ("source_id", "display_bap")}
    return sorted(row.business_key for row in inventory.campaign.inventory.filter(
        project_code=inventory.project_code, fiscal_year=inventory.fiscal_year, present=True
    ).exclude(pk=inventory.pk) if {k: v for k, v in row.data.items() if k not in ("source_id", "display_bap")} == content)


def carry_business_actions(campaign, *, progress=None):
    """Réapplique les corrections/liens identiques après initialisation des contrôles.

    Chaque ligne est atomique : échec de droits, capacité ou unicité => proposition
    auditée sans correction partielle. Les sources et décisions antérieures restent
    intactes. Les annulations ne sont pas reprises. Aucune preuve moteur n'est créée.
    Les propositions non résolues restent visibles à la campagne suivante.
    `progress`, optionnel, signale l'avancement par lots au worker d'import.
    Le BAP d'affichage, absent des anciens inventaires, ne déclenche pas à lui
    seul une rupture de reprise ; tous les anciens champs restent contrôlés.
    """
    previous = campaign.previous
    if not previous:
        return
    sources = list(previous.inventory.filter(present=True).filter(
        Q(adjustment__active=True) | Q(inventory_match__active=True) | Q(business_events__kind="CARRY_PENDING")
    ).select_related("adjustment__actor", "inventory_match__actor").distinct())
    if not sources:
        return
    current = {row.business_key: row for row in campaign.inventory.filter(
        present=True, business_key__in=[old.business_key for old in sources])}
    old_index, new_index = defaultdict(list), defaultdict(list)
    projects = {row.project_code for row in sources if getattr(row, "inventory_match", None)}
    for entry in previous.sage_inventory.filter(project_code__in=projects).iterator(chunk_size=500):
        old_index[sage_identity(entry)].append(entry)
    for entry in campaign.sage_inventory.filter(project_code__in=projects).iterator(chunk_size=500):
        new_index[sage_identity(entry)].append(entry)
    policy_same = all(previous.metadata.get(k) == campaign.metadata.get(k)
                      for k in ("amount_field", "tolerance", "sage_exclusions"))
    # Prépare les identités une seule fois pour toute la campagne.
    plans = []
    for old in sources:
        target = current.get(old.business_key)
        if target is None or target.business_version or target.business_events.filter(kind__in=["CARRY", "CARRY_PENDING"]).exists():
            continue
        correction, link = getattr(old, "adjustment", None), getattr(old, "inventory_match", None)
        correction = correction if correction and correction.active else None
        link = link if link and link.active else None
        if not correction and not link:
            pending = old.business_events.filter(kind="CARRY_PENDING").first()
            if pending and old.business_version == 0:
                CampaignAction.objects.create(inventory=target, request_id=uuid4(),
                    request_hash=digest(pending.after), kind="CARRY_PENDING", after=pending.after)
            continue
        proposal = {"origin_inventory": old.pk, "origin_campaign": previous.pk,
                    "adjustment": {"reason": correction.reason, "amount": str(correction.amount) if correction.amount is not None else None,
                                   "comment": correction.comment} if correction else None,
                    "link": manual_link_snapshot(link)}
        reasons, entries = [], []
        old_source = {k: v for k, v in old.data.items() if k != "display_bap"}
        target_source = {k: v for k, v in target.data.items() if k != "display_bap"}
        if old_source != target_source or (old.project_code, old.fiscal_year, old.source_id) != (target.project_code, target.fiscal_year, target.source_id):
            reasons.append("Les données Atlas ont changé.")
        if not policy_same:
            reasons.append("La politique de calcul a changé.")
        if correction and correction.reason == "DUPLICATE":
            witnesses = duplicate_witnesses(old)
            if not witnesses or witnesses != duplicate_witnesses(target):
                reasons.append("Le doublon justifiant l'exclusion n'est pas retrouvé à l'identique.")
        if link:
            if link.adjustment_version != adjustment_version(old):
                reasons.append("La correspondance précédente nécessite déjà une confirmation.")
            for allocation in link.allocations.filter(active=True).select_related("entry"):
                identity = sage_identity(allocation.entry)
                matches = new_index[identity]
                if len(old_index[identity]) != 1 or len(matches) != 1:
                    reasons.append("Une écriture Sage est absente, modifiée ou ambiguë.")
                else:
                    entries.append(matches[0].pk)
            if not entries:
                reasons.append("Aucune sélection Sage complète à reprendre.")
        plans.append((old, target, correction, link, proposal, reasons, entries))
    # Les corrections sans lien libèrent d'abord leurs capacités comptables.
    plans.sort(key=lambda plan: bool(plan[3]))
    # Un même lot atomique par ligne conserve correction et lien indissociables.
    for number, (old, target, correction, link, proposal, reasons, entries) in enumerate(plans, 1):
        if not reasons:
            try:
                with transaction.atomic():
                    if any(obj and (obj.actor is None or not obj.actor.is_active) for obj in (correction, link)):
                        raise PermissionDenied
                    if correction:
                        target = correct_inventory(target.pk, correction.actor, reason=correction.reason,
                            amount=correction.amount, comment=correction.comment, expected_version=target.business_version)
                    if link:
                        target = confirm_inventory_link(target.pk, link.actor, entry_ids=entries,
                            comment=link.comment, expected_version=target.business_version, replace_existing=True)
                    CampaignAction.objects.create(inventory=target, request_id=uuid4(), request_hash=digest(proposal),
                        kind="CARRY", after={**proposal, "automatic": True}, actor=None)
                    if link:
                        CampaignReview.objects.filter(campaign=campaign, line__transaction__business_key=target.business_key).update(
                            comparison="CARRIED", reasons=["Rapprochement manuel repris : sources identiques et capacité vérifiée."])
            except (ValidationError, PermissionDenied):
                reasons.append("Reprise à confirmer : droits, disponibilité ou capacité incompatibles.")
        if reasons:
            CampaignAction.objects.create(inventory=target, request_id=uuid4(), request_hash=digest(proposal),
                kind="CARRY_PENDING", after={**proposal, "reasons": list(dict.fromkeys(reasons))})
        if progress and number % 50 == 0:
            progress("Reprise des actions métier contrôlée", number)
