"""Agrégats de cadrage fondés sur les inventaires et résultats courants existants."""

from collections import defaultdict
from decimal import Decimal
from itertools import islice

from django.db import transaction
from reconciliation_contract import money
from reconciliation_contract.sage_inventory import CAPABILITY
from reconciliation_contract.ods_party import party_context

from .accounting_models import AccountingGroup, AccountingProject
from .models import Campaign, CampaignReview

ZERO = Decimal(0)
STATES = [("CADRE", "Cadré"), ("INSUFFISANT", "Données insuffisantes"), ("NON_CADRE", "Non cadré")]


def accounting_state(atlas, sage, insufficient=False):
    """Retourne état et écart arrondi selon Decimal/quantize existant ; aucune mutation.

    Les paramètres sont des Decimal EUR ou None ; insufficient signale un
    périmètre indéterminable. Un écart local peut être compensé au niveau projet.
    """
    gap = (atlas - sage).quantize(Decimal("0.01")) if atlas is not None and sage is not None else None
    return ("INSUFFISANT" if insufficient or gap is None else "CADRE" if gap == 0 else "NON_CADRE"), gap


def new_bucket():
    """Retourne un poste numérique indépendant ; réservé aux agrégats internes EUR."""
    return {"initial": ZERO, "atlas": ZERO, "sage": ZERO, "outside_atlas": ZERO, "groups": 0}


@party_context()
@transaction.atomic
def refresh_project(campaign, project):
    """Matérialise un projet sous verrou campagne, sans rejouer décisions ou moteur.

    Lit les contrôles par lots de 100 et les inventaires en flux ; les index
    numériques Sage et de dédoublonnage sont bornés au seul projet courant.
    Toutes les écritures Sage éligibles contribuent, rattachées ou non.
    Les anomalies individuelles restent des diagnostics non bloquants.
    Retourne AccountingProject. Toute erreur annule la projection précédente.
    Les appels métier fournissent une campagne déjà verrouillée ; ce verrou
    garantit également la cohérence d'une préparation explicite concurrente.
    """
    from .business import source_amount, retained_amount
    from .accounting_scope import ensure_controls, sage_scope, restore_unprojected
    from .accounting_oda import oda_diagnostic
    Campaign.all_objects.select_for_update().get(pk=campaign.pk)
    if CAPABILITY in campaign.metadata.get("capabilities", []):
        ensure_controls(campaign, project)
    sage, diagnostics, scope_issues, duplicates = sage_scope(campaign, project)
    buckets = defaultdict(new_bucket)
    issues, confirmed, source_types = set(), set(), defaultdict(set)
    projected_ids, missing_projection = set(), defaultdict(lambda: ZERO)
    missing_initial, missing_atlas, missing_sage, missing_status, missing_totals = set(), set(), set(), set(), set()
    sums = defaultdict(lambda: ZERO)
    for name in ("initial", "accounted_initial", "sent_initial", "confirmed", "pending_initial", "confirmed_initial",
                 "accounted_expected", "accounted_projected", "unattached_sage", "excluded_sage", "outside_atlas"):
        sums[name] = ZERO
    counts = defaultdict(int)
    counts["technical_duplicates"] = duplicates
    issues.update(scope_issues)
    if CAPABILITY not in campaign.metadata.get("capabilities", []) or not campaign.inventory_complete:
        issues.add("Inventaire comptable complet indisponible")
    quality = campaign.metadata.get("load_quality", {})
    if quality.get("sage", {}).get("invalid_accounting_dates", 0):
        issues.add("Dates Sage invalides dans l'extraction : périmètre incomplet")
    if quality.get("atlas", {}).get("conflicting_ids", 0):
        issues.add("Conflits d'identité Atlas dans l'extraction : total non fiable")
    line_sources = {str(line): source.get("source_id") for line, source in
        CampaignReview.objects.filter(campaign=campaign, project__code=project).values_list("line_id", "source").iterator(chunk_size=500)}
    inventories = list(campaign.inventory.filter(project_code=project, present=True).select_related("adjustment").iterator(chunk_size=500))
    for row in inventories:
        # Réutiliser l'objet campagne évite de redécoder ses métadonnées par ligne.
        row.campaign = campaign
    oda_sources = defaultdict(list)
    accounted_sources = defaultdict(list)
    for row in inventories:
        if row.data.get("bap_status") == "Comptabilisé":
            accounted_sources[row.control_key].append(row)
        if row.data.get("bap_status") != "Comptabilisé" or not str(row.data.get("sage_document_number") or "").startswith("ODA"):
            continue
        if campaign.metadata.get("amount_field") not in ("total_sage_charges", "total_project_charges"):
            continue
        if getattr(row, "adjustment", None) and row.adjustment.active and row.adjustment.reason == "DUPLICATE":
            continue
        retained = retained_amount(row)
        oda_sources[row.control_key].append({**row.data, campaign.metadata["amount_field"]:
                                             str(retained) if retained is not None else None})
    stream = campaign.global_controls.filter(project_code=project).order_by("key").iterator(chunk_size=100)
    AccountingGroup.objects.filter(campaign=campaign, project_code=project).delete()
    processed = 0
    while batch := list(islice(stream, 100)):
        group_rows = []
        for control in batch:
            processed += 1
            data, item = control.current_data or control.data, sage[control.key]
            diagnostics.update(data.get("reasons", []))
            projected_ids.update(tuple(source) for source in data.get("atlas_ids", []))
            allocations = data.get("confirmed_allocations", [])
            bound = bool(data.get("atlas_count") or allocations)
            accounted = money(data.get("accounted_total"))
            sent = money(data.get("confirmed_sent_total"))
            a = accounted + sent if accounted is not None and sent is not None else None
            sums["accounted_projected"] += accounted if accounted is not None else ZERO
            sums["confirmed"] += sent if sent is not None else ZERO
            types = item["types"]
            identity = data["identity"]
            kind = next(iter(types)) if len(types) == 1 else "MIXTE" if types else (
                identity["parts"][2][:3] if identity["strategy"] == "STANDARD_BY_DOCUMENT" else "ODS/ODG")
            kind = kind or "NA"
            for allocation in allocations:
                key = str(allocation["line_key"])
                source = key if key.startswith("inventory:") else line_sources.get(key)
                if source is None:
                    issues.add("Source d'une confirmation non identifiable")
                else:
                    confirmed.add(source)
                    source_types[source].add(kind)
            excluded = bool(item["excluded_n"] and not item["n"])
            sums["excluded_sage"] += item["excluded"]
            counts["excluded_sage"] += item["excluded_n"]
            if not bound:
                sums["unattached_sage"] += item["amount"]
                counts["unattached_sage"] += item["n"]
            if item["missing"]:
                missing_sage.add(kind)
                missing_totals.add("sage")
                if not bound:
                    missing_totals.add("unattached_sage")
                issues.add("Montant Sage éligible absent : total incomplet")
            if item["excluded_missing"]:
                missing_totals.add("excluded_sage")
            retained_sage = item["amount"]
            outside = a if excluded and a is not None else ZERO
            if item["n"] and item["excluded_n"] and a is not None:
                excluded_types = item["excluded_types"] - item["eligible_types"]
                group_ids = {tuple(source) for source in data.get("atlas_ids", [])}
                outside = sum((retained_amount(row) or ZERO for row in accounted_sources[control.key]
                    if (project, row.fiscal_year, row.source_id) in group_ids
                    and str(row.data.get("sage_document_number") or "")[:3].upper() in excluded_types), ZERO)
            retained_atlas = a - outside if bound and a is not None else ZERO
            local_issue = bool((bound and a is None) or item["missing"])
            # Les anomalies de correspondance ne deviennent pas une seconde fiabilité.
            # Seuls les manques empêchant de déterminer le périmètre bloquent le calcul.
            if local_issue:
                issues.add("Certains groupes ont des données insuffisantes pour déterminer le périmètre")
            if bound and a is None:
                missing_atlas.add(kind)
            if excluded or outside:
                sums["outside_atlas"] += outside
                buckets[kind]["outside_atlas"] += outside
            bucket = buckets[kind]
            bucket["atlas"] += retained_atlas
            bucket["sage"] += retained_sage
            bucket["groups"] += 1
            state, gap = accounting_state(retained_atlas, retained_sage, local_issue)
            oda = oda_diagnostic(identity, oda_sources[control.key], item["entries"],
                amount_field=campaign.metadata.get("amount_field"), tolerance=campaign.metadata.get("tolerance", "0.01"))
            if oda and (allocations or any(row.get("manual_link") for row in data.get("business_provenance", []))):
                oda["reliable"] = False
                oda["reasons"].append("Affectations existantes : contrôle métier individuel à conserver")
            if local_issue:
                gap = None
            group_rows.append(AccountingGroup(control=control, campaign=campaign, project_code=project, piece_type=kind,
                atlas=retained_atlas if not local_issue else None, sage=retained_sage if not item["missing"] else None,
                gap=gap, state=state, data={"identity": identity, "attached": bound, "excluded": excluded,
                    "unattached_sage": str(item["amount"] if not bound else ZERO),
                    "excluded_sage": str(item["excluded"]), "diagnostics": data.get("reasons", []),
                    "totals": {"atlas": str(retained_atlas) if not (bound and a is None) else None,
                               "sage": str(retained_sage) if not item["missing"] else None},
                    **({"oda": oda} if oda else {})}))
        AccountingGroup.objects.bulk_create(group_rows, batch_size=100)
    for inventory in inventories:
        status = inventory.data.get("bap_status")
        if status not in ("Comptabilisé", "Envoyé SAGE"):
            continue
        original, retained = source_amount(inventory), retained_amount(inventory)
        original_missing = original is None
        if status == "Comptabilisé" and (original is None or retained is None):
            issues.add("Montant Atlas source ou retenu absent")
        if status == "Comptabilisé" and campaign.metadata.get("amount_field") not in ("total_sage_charges", "total_project_charges"):
            issues.add("Sémantique du montant Atlas non confirmée")
        if status == "Comptabilisé" and (not project or inventory.fiscal_year is None
                or campaign.fiscal_year is not None and inventory.fiscal_year != campaign.fiscal_year):
            issues.add("Projet ou exercice Atlas indéterminable ou hors campagne")
        original = original if original is not None else ZERO
        retained = retained if retained is not None else ZERO
        sums["initial"] += original
        if status == "Comptabilisé":
            sums["accounted_initial"] += original
            sums["accounted_expected"] += retained
            if (project, inventory.fiscal_year, inventory.source_id) not in projected_ids:
                missing_projection[inventory.control_key] += retained
            kind = inventory.data.get("sage_document_number", "")[:3].upper() or "NA"
        else:
            sums["sent_initial"] += original
            key = "inventory:" + str(inventory.pk)
            source = key if key in confirmed else inventory.source_id
            if source in confirmed:
                sums["confirmed_initial"] += original
                kinds = source_types[source]
                kind = next(iter(kinds)) if len(kinds) == 1 else "MIXTE"
            else:
                kind = "NA"
                sums["pending_initial"] += original
        buckets[kind]["initial"] += original
        if original_missing:
            missing_initial.add(kind)
            missing_status.add("accounted_initial" if status == "Comptabilisé" else "sent_initial")
            if status == "Envoyé SAGE":
                missing_totals.add("confirmed_initial" if source in confirmed else "pending_initial")
    residual = sums["accounted_expected"] - sums["accounted_projected"]
    if residual:
        # Un lien périmé peut retirer une projection ; ne pas faire disparaître Atlas.
        remaining = restore_unprojected(campaign, project, missing_projection, residual, buckets)
        if remaining and not issues:
            issues.add("Projection Atlas contradictoire : total retenu non attribuable aux sources")
        diagnostics.add("Montant comptabilisé non attribuable aux contrôles courants")
    if not processed and (sums["accounted_initial"] or sums["confirmed"]):
        diagnostics.add("Contrôles courants indisponibles")
    sums["atlas"] = sum((b["atlas"] for b in buckets.values()), ZERO)
    sums["sage"] = sum((b["sage"] for b in buckets.values()), ZERO)
    sums["adjustments"] = sums["accounted_expected"] + sums["confirmed"] - sums["accounted_initial"] - sums["confirmed_initial"]
    state, gap = accounting_state(sums["atlas"], sums["sage"], bool(issues))
    types = []
    for kind, bucket in sorted(buckets.items()):
        post = {"type": kind, **{k: str(v) if isinstance(v, Decimal) else v for k, v in bucket.items()},
                "gap": str((bucket["atlas"] - bucket["sage"]).quantize(Decimal("0.01"))),
                "has_outside": bucket["outside_atlas"] != ZERO}
        for field, missing in (("initial", missing_initial), ("atlas", missing_atlas), ("sage", missing_sage)):
            if kind in missing:
                post[field] = None
        if post["atlas"] is None or post["sage"] is None:
            post["gap"] = None
        types.append(post)
    totals = {k: str(v) for k, v in sums.items()}
    if missing_atlas or "accounted_initial" in missing_status:
        totals["atlas"] = None
    if scope_issues or quality.get("sage", {}).get("invalid_accounting_dates", 0):
        totals["sage"] = None
    if CAPABILITY not in campaign.metadata.get("capabilities", []) or not campaign.inventory_complete:
        totals["atlas"] = totals["sage"] = None
    for field in missing_totals | missing_status:
        totals[field] = None
    if missing_initial:
        totals["initial"] = None
        totals["adjustments"] = None
    data = {"totals": totals, "counts": dict(counts), "types": types,
            "issues": sorted(issues), "diagnostics": sorted(diagnostics), "prepared": True,
            "accounting_policy": "exhaustive-sage-v1"}
    result, _ = AccountingProject.objects.update_or_create(campaign=campaign, project_code=project, defaults={
        "atlas": sums["atlas"] if not issues else None, "sage": sums["sage"] if not issues else None,
        "gap": gap if not issues else None, "state": state, "data": data})
    return result


def prepare_campaign(campaign, *, progress=None):
    """Prépare les projets importés en flux ; retourne leur nombre, sans moteur ni décision.

    Appelé après import ou par commande explicite ; chaque projet est atomique.
    Les campagnes historiques ne sont lues que si explicitement demandées.
    progress reçoit l'étape et le nombre de projets préparés, si fourni.
    """
    codes = campaign.inventory.filter(present=True).values_list("project_code", flat=True).union(
        campaign.sage_inventory.values_list("project_code", flat=True)).order_by("project_code")
    count = 0
    for code in codes.iterator(chunk_size=100):
        refresh_project(campaign, code)
        count += 1
        if progress:
            progress("Cadrage comptable préparé", count)
    return count
