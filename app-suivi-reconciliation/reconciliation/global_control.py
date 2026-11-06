"""API interne du contrôle global ; aucune tâche permanente ni déclencheur de validation."""

from collections import defaultdict
from decimal import Decimal
from itertools import islice
from typing import Iterator

from django.core.exceptions import ValidationError
from reconciliation_contract import ODS, control_identity, digest, money
from reconciliation_contract.sage_inventory import CAPABILITY, consolidate, ods_scope

from .models import CampaignGlobalControl, CampaignReview, ControlContribution


def campaign_controls(campaign, *, keys: list[str] | None = None) -> Iterator[dict]:
    """Retourne en flux les contrôles actuels d'une campagne ou des `keys` ciblées.

    Lève ValidationError si l'ancien fichier n'a pas l'inventaire Sage. Lit au
    plus cent groupes par lot, jamais tout l'inventaire ; les grosses pièces
    occupent la mémoire de leur lot. Les campagnes closes utilisent leurs
    décisions photographiées ; les campagnes courantes vérifient aussi la
    fraîcheur applicative. Aucun écrit ni effet sur une validation utilisateur.
    Le Lot 2 projette les corrections et liens de campagne puis appelle cette
    API sous verrou Campaign ; seules les clés demandées sont recalculées et
    les sources/diagnostics initiaux restent immuables.
    """
    if CAPABILITY not in campaign.metadata.get("capabilities", []):
        raise ValidationError("Contrôle global indisponible pour cette campagne")
    sage_keys = campaign.sage_inventory.values_list("control_key", flat=True)
    atlas_keys = campaign.inventory.filter(present=True, data__bap_status="Comptabilisé").values_list("control_key", flat=True)
    all_keys = sage_keys.union(atlas_keys).order_by("control_key")
    key_stream = iter(keys) if keys is not None else all_keys.iterator(chunk_size=100)
    while batch := list(islice(key_stream, 100)):
        sage, atlas, allocations = defaultdict(list), defaultdict(list), defaultdict(list)
        for key, data in campaign.sage_inventory.filter(control_key__in=batch).values_list("control_key", "data").iterator(chunk_size=500):
            sage[key].append(data)
        for key, data in campaign.inventory.filter(control_key__in=batch, present=True, data__bap_status="Comptabilisé").values_list("control_key", "data").iterator(chunk_size=500):
            atlas[key].append(data)
        from django.db.models import Count, Q
        scopes = {ods_scope(r["entry"], sage=True) for rows in sage.values() for r in rows}
        scopes.update(ods_scope(a) for sources in atlas.values() for a in sources)
        scopes.discard("")
        sage_counts = dict(campaign.sage_inventory.filter(ods_scope__in=scopes).values("ods_scope").annotate(n=Count("pk")).values_list("ods_scope", "n"))
        atlas_counts = dict(campaign.inventory.filter(ods_scope__in=scopes, present=True, data__bap_status="Comptabilisé").exclude(
            adjustment__active=True, adjustment__reason="DUPLICATE").values("ods_scope").annotate(n=Count("pk")).values_list("ods_scope", "n"))
        projects = {r["entry"]["project_code"] for rows in sage.values() for r in rows}
        projects.update(a["project_code"] for sources in atlas.values() for a in sources)
        uncertain = set(campaign.sage_inventory.filter(project_code__in=projects).filter(Q(fiscal_year__isnull=True) | Q(document="")).values_list("project_code", flat=True).distinct())
        contributions = list(ControlContribution.objects.filter(control__campaign=campaign, control__key__in=batch).select_related(
            "control", "line__transaction__project", "line__group", "line__campaign"))
        frozen = {r.line_id: r for r in CampaignReview.objects.filter(campaign=campaign, line_id__in=[c.line_id for c in contributions])}
        # Une ligne répartie entre pièces n'est admise que si toutes ses
        # contributions totalisent son montant effectif validé.
        totals = defaultdict(lambda: Decimal(0))
        for line_id, amount in ControlContribution.objects.filter(control__campaign=campaign, line_id__in=frozen).values_list("line_id", "amount").iterator(chunk_size=500):
            totals[line_id] += amount
        from .review import is_current
        invalid = set()
        for contribution in contributions:
            review = frozen.get(contribution.line_id)
            decision = review.decision if review else {}
            resolved = decision.get("effective", {})
            current = decision.get("current", False)
            if campaign.is_current:
                current = (current and contribution.line.campaign_id == campaign.pk
                           and contribution.line.state == "VALIDATED" and is_current(contribution.line))
            valid = decision.get("state") == "VALIDATED" and current
            if valid and money(resolved.get("amount")) != totals.get(contribution.line_id):
                invalid.add(contribution.control.key)
            allocations[contribution.control.key].append({
                "line_key": str(contribution.line_id), "amount": str(contribution.amount),
                "refs": contribution.entries, "validated": decision.get("state") == "VALIDATED",
                "partial_validated": decision.get("validation_source") == "MANUAL" and len(contribution.entries) == 1,
                "current": current, "source_status": review.source.get("bap_status") if review else None})
        identities = {key: control_identity(sage[key][0]["entry"], sage=True) if sage[key] else control_identity(atlas[key][0])
                      for key in batch if sage[key] or atlas[key]}
        from .business_calculation import business_inputs
        business_reasons, provenance = business_inputs(campaign, batch, atlas, allocations, contributions, frozen)
        summary = campaign.metadata.get("load_quality", {})
        for key in batch:
            rows, sources = sage[key], atlas[key]
            if key not in identities:
                continue
            identity = identities[key]
            reasons = list(business_reasons[key])
            manual_ods = (identity["strategy"] == ODS and any(p.get("manual_link") and p.get("current") for p in provenance[key])
                          and all(a.get("manual_inventory_link") for a in sources)
                          and all(a.get("manual_inventory") for a in allocations[key]))
            if identity["parts"][0] in uncertain:
                reasons.append("Identités Sage incomplètes dans le projet")
            if identity["strategy"] == ODS and not identity["parts"][-1] and not manual_ods:
                scope = ods_scope(rows[0]["entry"], sage=True) if rows else ods_scope(sources[0])
                if sage_counts.get(scope, 0) != 1 or atlas_counts.get(scope, 0) != 1:
                    reasons.append("Candidats concurrents ODS/ODG sur projet/exercice/tiers")
            if key in invalid:
                reasons.append("Somme des affectations différente du montant effectif validé")
            if summary.get("atlas", {}).get("conflicting_ids", 0):
                reasons.append("Conflits d'identité Atlas dans l'extraction")
            if summary.get("sage", {}).get("invalid_accounting_dates", 0):
                reasons.append("Dates Sage invalides : périmètre incomplet")
            data = consolidate(identity, sources, rows, allocations[key],
                               amount_field=campaign.metadata["amount_field"],
                               tolerance=campaign.metadata["tolerance"], scope_reasons=reasons, manual_ods=manual_ods)
            if provenance[key]:
                data.pop("signature")
                data["business_provenance"] = provenance[key]
                data["auto_validated"] = False
                data["signature"] = digest(data)
            yield data


def initialize_controls(campaign, *, progress=None) -> None:
    """Persiste le calcul initial en lots de 500 dans la transaction d'import.

    Appelé après auto-validations et reports existants ; une erreur annule la
    publication entière. Les recalculs futurs utilisent campaign_controls sans
    remplacer ces preuves initiales ni réécrire une campagne antérieure.
    """
    batch, count = [], 0
    for data in campaign_controls(campaign):
        batch.append(CampaignGlobalControl(campaign=campaign, key=data["key"],
                     project_code=data["identity"]["parts"][0], state=data["state"], data=data))
        count += 1
        if len(batch) == 500:
            CampaignGlobalControl.objects.bulk_create(batch, batch_size=500)
            batch.clear()
            if progress:
                progress("Contrôles globaux préparés", count)
    if batch:
        CampaignGlobalControl.objects.bulk_create(batch, batch_size=500)
