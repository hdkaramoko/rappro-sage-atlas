"""Périmètre Sage exhaustif du cadrage, indépendant des associations Atlas."""

from collections import defaultdict
from decimal import Decimal
from itertools import islice

from django.db.models import Count, Q
from django.db.models.fields.json import KeyTextTransform

from reconciliation_contract import control_identity, digest, money
from reconciliation_contract.sage_inventory import consolidate

from .models import CampaignGlobalControl


def ensure_controls(campaign, project):
    """Crée seulement les contrôles manquants depuis les inventaires, sans toucher aux contrôles existants.

    L'appelant détient le verrou campagne. Les lectures sont groupées par cinq cents
    clés ; aucune source ni décision n'est modifiée. Retourne None.
    """
    existing = campaign.global_controls.filter(project_code=project).values("key")
    sage = campaign.sage_inventory.filter(project_code=project).exclude(control_key__in=existing).values_list("control_key", flat=True)
    atlas = campaign.inventory.filter(project_code=project, present=True, data__bap_status="Comptabilisé").exclude(
        control_key__in=existing).values_list("control_key", flat=True)
    keys = iter(sage.union(atlas).order_by("control_key"))
    from .business_calculation import business_inputs
    while batch := list(islice(keys, 500)):
        records, sources, allocations = defaultdict(list), defaultdict(list), defaultdict(list)
        for key, data in campaign.sage_inventory.filter(project_code=project, control_key__in=batch).values_list("control_key", "data").iterator(chunk_size=500):
            records[key].append(data)
        for key, data in campaign.inventory.filter(project_code=project, present=True,
                data__bap_status="Comptabilisé", control_key__in=batch).values_list("control_key", "data").iterator(chunk_size=500):
            sources[key].append(data)
        initial_sources = {key: list(rows) for key, rows in sources.items()}
        reasons, provenance = business_inputs(campaign, batch, sources, allocations, [], {})
        rows = []
        for key in batch:
            entry = records[key][0]["entry"] if records[key] else None
            identity = control_identity(entry, sage=True) if entry else control_identity(initial_sources[key][0])
            initial = consolidate(identity, initial_sources.get(key, []), records[key], [],
                amount_field=campaign.metadata["amount_field"], tolerance=campaign.metadata["tolerance"],
                scope_reasons=["Contrôle reconstruit depuis les inventaires ; aucune décision créée"])
            current = consolidate(identity, sources[key], records[key], allocations[key],
                amount_field=campaign.metadata["amount_field"], tolerance=campaign.metadata["tolerance"],
                scope_reasons=reasons[key])
            if provenance[key]:
                current.pop("signature")
                current["business_provenance"] = provenance[key]
                current["auto_validated"] = False
                current["signature"] = digest(current)
            rows.append(CampaignGlobalControl(campaign=campaign, key=key, project_code=project,
                state=initial["state"], data=initial, current_data=current, current_state=current["state"]))
        CampaignGlobalControl.objects.bulk_create(rows, batch_size=500)


def sage_scope(campaign, project):
    """Retourne postes Sage par contrôle, diagnostics et blocages réels du total projet.

    Un parcours numérique indexé du projet conserve les signes et neuf décimales.
    Le JSON n'est lu que pour les ODA et les références répétées à expertiser.
    Le montant canonique est extrait en SQL comme texte pour éviter la limite
    de précision des DecimalField SQLite, sans décoder tout le JSON en Python.
    Seuls les doublons de référence complète ET contenu canonique identique sont
    neutralisés ; les collisions différentes restent sommées et signalées.
    Aucun état de rapprochement ne définit l'éligibilité. Lecture seule.
    """
    groups = defaultdict(lambda: {"amount": Decimal(0), "excluded": Decimal(0), "n": 0, "excluded_n": 0,
        "types": set(), "eligible_types": set(), "excluded_types": set(),
        "missing": False, "excluded_missing": False, "entries": []})
    seen, refs, diagnostics, issues = set(), set(), set(), set()
    duplicates = 0
    population = campaign.sage_inventory.filter(project_code=project)
    repeated = population.values("entry_ref").annotate(n=Count("pk")).filter(n__gt=1).values("entry_ref")
    details = {pk: data.get("entry", {}) for pk, data in population.filter(
        Q(document__startswith="ODA") | Q(entry_ref__in=repeated)).values_list("pk", "data").iterator(chunk_size=500)}
    rows = population.annotate(exact_amount=KeyTextTransform.from_lookup("data__entry__amount")).values_list(
        "pk", "control_key", "document", "amount", "eligible", "fiscal_year", "entry_ref", "exact_amount")
    for pk, key, document, amount, eligible, year, ref, exact in rows.iterator(chunk_size=500):
        if exact is not None and amount is not None:
            amount = money(exact)
        entry = details.get(pk, {})
        signature = (ref, digest(entry), amount, eligible) if entry else None
        if entry.get("identity_complete") and ref and signature in seen:
            duplicates += 1
            diagnostics.add("Doublon technique Sage identique neutralisé dans le cadrage")
            continue
        if ref in refs:
            diagnostics.add("Référence technique Sage répétée : ambiguïté individuelle conservée")
        refs.add(ref)
        if entry.get("identity_complete") and ref:
            seen.add(signature)
        if entry and not entry.get("identity_complete"):
            diagnostics.add("Identité Sage incomplète : montant inclus si le périmètre est connu")
        item = groups[key]
        item["types"].add(document[:3].upper() or "NA")
        item["eligible_types" if eligible else "excluded_types"].add(document[:3].upper() or "NA")
        item["missing" if eligible else "excluded_missing"] |= amount is None
        item["amount" if eligible else "excluded"] += amount if amount is not None else Decimal(0)
        item["n" if eligible else "excluded_n"] += 1
        if eligible and (not project or year is None or campaign.fiscal_year is not None and year != campaign.fiscal_year):
            issues.add("Projet ou exercice Sage indéterminable ou hors campagne")
        if eligible and document.upper().startswith("ODA"):
            item["entries"].append(entry or {"project_code": project, "fiscal_year": year,
                "document": document, "amount": str(amount) if amount is not None else None,
                "ref": ref, "identity_complete": False})
    return groups, diagnostics, issues, duplicates


def restore_unprojected(campaign, project, missing, residual, buckets):
    """Réintègre un retenu Atlas omis par un lien périmé dans son propre groupe source.

    Ne crée aucune affectation Sage et ne choisit aucune pièce par montant.
    L'appelant fournit les sources absentes des atlas_ids projetés ; le reste
    non attribuable est retourné, sans inventer un poste ni modifier la source.
    """
    from .accounting import accounting_state
    from .accounting_models import AccountingGroup
    pending = residual
    keys = iter(sorted(missing))
    while batch := list(islice(keys, 500)):
        changed = []
        rows = AccountingGroup.objects.filter(campaign=campaign, project_code=project,
            control__key__in=batch).select_related("control")
        for group in rows:
            amount = missing[group.control.key]
            if pending == 0 or pending * amount <= 0 or group.atlas is None or group.data.get("excluded"):
                continue
            restored = min(abs(pending), abs(amount)) * (1 if pending > 0 else -1)
            group.atlas = Decimal(group.data.get("totals", {}).get("atlas") or group.atlas) + restored
            group.state, group.gap = accounting_state(group.atlas, group.sage)
            group.data["unprojected_atlas"] = str(restored)
            group.data.setdefault("totals", {})["atlas"] = str(group.atlas)
            group.data.setdefault("diagnostics", []).append("Retenu Atlas conservé dans sa pièce source ; rapprochement à revoir")
            buckets[group.piece_type]["atlas"] += restored
            pending -= restored
            changed.append(group)
        if changed:
            AccountingGroup.objects.bulk_update(changed, ["atlas", "gap", "state", "data"], batch_size=100)
    return pending
