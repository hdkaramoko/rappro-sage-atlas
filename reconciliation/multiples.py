"""Contrôles indépendants du préfiltre de matching, ciblés par clés Atlas utiles."""

from collections import defaultdict

from reconciliation.matching.trace import json_value
from reconciliation_contract import (
    EXTRA_INVENTORY,
    control_identity,
    digest,
    entry_from_sage,
    snapshot,
)
from decimal import Decimal

INVENTORY = {
    "Code projet": "project_code",
    "Année": "fiscal_year",
    "Id": "source_id",
    "Statut BAP": "bap_status",
    "Total charges projet (€)": "total_project_charges",
    "Total charges SAGE (€)": "total_sage_charges",
    "N° pièce SAGE": "sage_document_number",
    "Date comptable": "accounting_date",
    **EXTRA_INVENTORY,
}


def inventory_rows(atlas):
    """Parcourt les seuls champs du contrat, sans recopier toutes les colonnes Atlas."""
    canonical = atlas.reindex(columns=list(INVENTORY))
    for values in canonical[list(INVENTORY)].itertuples(index=False, name=None):
        row = json_value(dict(zip(INVENTORY.values(), values)))
        if row["accounting_date"]:
            row["accounting_date"] = str(row["accounting_date"])[:10]
        for name in ("total_sage_charges", "total_project_charges"):
            if row[name] is not None:
                row[name] = format(
                    Decimal(str(row[name])).quantize(Decimal("0.01")), "f"
                )
        for name in (
            "project_code",
            "source_id",
            "bap_status",
            "sage_document_number",
        ):
            row[name] = str(row[name] or "").strip()
        for name in EXTRA_INVENTORY.values():
            row[name] = str(row[name] or "")
        row["project_code"] = row["project_code"].upper()
        yield row


def build_controls(atlas, sage, result, *, amount_field="total_sage_charges", tolerance="0.01"):
    """Indexe les pièces utiles sur SAGE complet, sans produit Atlas × SAGE.

    Les lignes déjà comptabilisées sont les seules contributions sources.
    Les pièces des propositions sont aussi conservées pour les validations futures.
    """
    identities, accounted, evidence = {}, defaultdict(list), defaultdict(list)
    for row in inventory_rows(atlas):
        if row["bap_status"] not in ("Comptabilisé", "Envoyé SAGE"):
            continue
        identity = control_identity(row)
        key = digest(identity)
        identities[key] = identity
        if row["bap_status"] == "Comptabilisé":
            accounted[key].append(row)
    candidates = {g["group_id"]: g for g in result.attrs["sage_candidates"]}
    positions = {
        p
        for ids in result["candidate_ids"]
        for candidate in ids
        for p in candidates[candidate]["source_positions"]
    }
    for position in positions:
        entry = entry_from_sage(json_value(sage.iloc[position].to_dict()))
        identity = control_identity(entry, sage=True)
        identities[digest(identity)] = identity
    uncertain_projects = set()
    for raw in sage.itertuples(index=False, name=None):
        entry = entry_from_sage(json_value(dict(zip(sage.columns, raw))))
        if not entry["fiscal_year"] or not entry["document"]:
            uncertain_projects.add(entry["project_code"])
        key = digest(control_identity(entry, sage=True))
        if key in identities:
            evidence[key].append(entry)
    summary = atlas.attrs.get("load_summary", {})
    for key, identity in sorted(identities.items()):
        reasons = []
        if identity["parts"][0] in uncertain_projects or sage.attrs.get(
            "load_summary", {}
        ).get("invalid_accounting_dates", 0):
            reasons.append(
                "Des écritures SAGE sans date/pièce peuvent rendre le périmètre incomplet"
            )
        if summary.get("conflicting_ids", 0):
            reasons.append("Conflits d’Id Atlas : photographie non fiable")
        yield snapshot(
            identity,
            accounted[key],
            evidence[key],
            amount_field=amount_field,
            tolerance=tolerance,
            reasons=reasons,
        )
