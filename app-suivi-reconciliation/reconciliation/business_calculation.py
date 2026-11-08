"""Projection de calcul du Lot 2 ; les photographies sources restent immuables."""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Q
from reconciliation_contract import ODS, control_identity, money

from .business import adjustment_version, retained_amount
from .models import AtlasAdjustment, CampaignInventory, ManualAllocation


def business_inputs(campaign, keys, atlas, allocations, contributions, snapshots):
    """Projette corrections et liens dans les entrées Lot 1 des seuls groupes `keys`.

    Retourne motifs et provenance par clé. Corrige les Comptabilisé, invalide les
    confirmations dont la correction a changé et projette les liens explicites
    sur les références Sage réelles. Les clés cibles ODS ne sont utilisées que
    dans cette projection, jamais injectées dans les sources. Montants Decimal
    EUR, quelques lectures par lot, aucune écriture ni scan global de campagne.
    `snapshots` contient les décisions de cette campagne pour éviter de relire
    les versions mutables de revue lorsqu'une campagne est historique.
    Une projection manuelle ODS adapte uniquement le libellé technique sélectionné
    par le contrat (SAGE pour les nouvelles sources comptabilisées, ATLAS historique).
    """
    business_keys = {c.line.transaction.business_key for c in contributions}
    inventories = list(CampaignInventory.objects.filter(campaign=campaign, present=True).filter(
        Q(control_key__in=keys) | Q(business_key__in=business_keys) |
        Q(inventory_match__allocations__active=True, inventory_match__allocations__entry__control_key__in=keys)
    ).distinct().select_related("campaign", "adjustment", "inventory_match"))
    indexed = {i.business_key: i for i in inventories}
    by_identity = {(i.project_code, i.fiscal_year, i.source_id): i for i in inventories}
    reasons, provenance, manual = defaultdict(list), defaultdict(list), defaultdict(list)
    for allocation in ManualAllocation.objects.filter(link__inventory_id__in=[i.pk for i in inventories], active=True).select_related("entry").order_by("pk"):
        manual[allocation.link_id].append(allocation)
    for key in keys:
        adjusted = []
        for source in atlas[key]:
            inventory = by_identity.get((source["project_code"], source["fiscal_year"], source["source_id"]))
            if inventory is None:
                adjusted.append(source)
                continue
            correction = getattr(inventory, "adjustment", None)
            if correction and correction.active:
                provenance[key].append({"source_id": inventory.source_id, "reason": correction.reason,
                                        "version": correction.version, "retained": str(retained_amount(inventory))})
                if correction.reason == AtlasAdjustment.Reason.DUPLICATE:
                    continue
                source = {**source, campaign.metadata["amount_field"]: str(correction.amount)}
            link = getattr(inventory, "inventory_match", None)
            if not link or not link.active:
                adjusted.append(source)
        atlas[key] = adjusted
    for contribution in contributions:
        inventory = indexed.get(contribution.line.transaction.business_key)
        if not inventory:
            continue
        for allocation in allocations[contribution.control.key]:
            if allocation["line_key"] != str(contribution.line_id):
                continue
            correction = getattr(inventory, "adjustment", None)
            frozen = snapshots.get(contribution.line_id)
            decision = frozen.decision if frozen else {}
            if decision.get("inventory_link"):
                allocation["current"] = False
            elif correction and correction.active and correction.reason == AtlasAdjustment.Reason.DUPLICATE:
                allocation["current"] = False
            elif (adjustment_version(inventory) != decision.get("adjustment_version", 0)
                  or correction and correction.active and not allocation["current"]):
                allocation["current"] = False
                reasons[contribution.control.key].append("Correction métier modifiée : confirmation à revoir")
    for inventory in inventories:
        link = getattr(inventory, "inventory_match", None)
        if not link or not link.active:
            continue
        selected = manual[link.pk]
        retained = retained_amount(inventory)
        amounts = [money(a.entry.data["entry"]["amount"]) for a in selected]
        total = sum(amounts, Decimal(0)) if all(a is not None for a in amounts) else None
        correction = getattr(inventory, "adjustment", None)
        valid = (bool(selected) and total is not None and retained is not None and retained == link.amount
                 and adjustment_version(inventory) == link.adjustment_version
                 and abs(total - retained) <= money(campaign.metadata["tolerance"])
                 and not (correction and correction.active and correction.reason == AtlasAdjustment.Reason.DUPLICATE))
        grouped = defaultdict(list)
        for allocation in selected:
            grouped[allocation.entry.control_key].append(allocation)
        for key in {inventory.control_key, *grouped} & set(keys):
            provenance[key].append({"source_id": inventory.source_id, "manual_link": link.pk,
                                    "version": link.version, "current": valid})
            if not valid:
                reasons[key].append("Rapprochement manuel à revoir après modification métier")
        for key, entries in grouped.items():
            if key not in keys or not valid:
                continue
            amount = sum((money(a.entry.data["entry"]["amount"]) for a in entries), Decimal(0))
            if inventory.data["bap_status"] == "Comptabilisé":
                identity = control_identity(entries[0].entry.data["entry"], sage=True)
                source = {**inventory.data, campaign.metadata["amount_field"]: str(amount), "manual_inventory_link": link.pk}
                if identity["strategy"] == ODS:
                    source["sage_third_party_code"] = identity["parts"][2]
                    source["sage_label" if "sage_label" in source else "atlas_label"] = identity["parts"][3]
                else:
                    source["sage_document_number"] = identity["parts"][2]
                atlas[key].append(source)
            else:
                allocations[key].append({"line_key": f"inventory:{inventory.pk}", "amount": str(amount),
                                         "refs": [a.entry.entry_ref for a in entries], "validated": True,
                                         "current": True, "source_status": "Envoyé SAGE", "manual_inventory": True})
    return reasons, provenance
