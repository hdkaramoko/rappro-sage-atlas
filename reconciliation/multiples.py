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
from reconciliation_contract.ods_party import party_context

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
    "Libellé SAGE": "sage_label",
}


def inventory_rows(atlas):
    """Retourne en flux les dictionnaires canoniques Atlas du DataFrame `atlas`.

    Conserve les champs v3 et les montants individuels en chaînes EUR à deux
    décimales. Les colonnes décimales du loader priment sur les flottants du
    matching ; None reste distinct de zéro et les signes sont conservés.
    Aucune mutation de la source ni écriture de fichier/base.
    Libellé SAGE est conservé séparément, vide si absent, pour les contrôles ODS
    comptabilisés. Il ne remplace jamais le libellé utilisé par le matching Envoyé.
    """
    canonical = atlas.reindex(columns=list(INVENTORY)).copy()
    for column, origin in (("Total charges SAGE (€)", "_total_sage_decimal"),
                           ("Total charges projet (€)", "_total_project_decimal")):
        if origin in atlas:
            canonical[column] = atlas[origin]
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
        for name in (*EXTRA_INVENTORY.values(), "sage_label"):
            row[name] = str(row[name] or "")
        row["project_code"] = row["project_code"].upper()
        yield row


@party_context(new=True)
def build_controls(atlas, sage, result, *, amount_field="total_sage_charges", tolerance="0.01", excluded_prefixes=None):
    """Indexe les pièces utiles sur SAGE complet, sans produit Atlas × SAGE.

    Les lignes déjà comptabilisées sont les seules contributions sources.
    Les pièces des propositions sont aussi conservées pour les validations futures.
    `excluded_prefixes`, liste optionnelle de préfixes de trois caractères, rend
    les contrôles concernés UNKNOWN sans filtrer les candidats de la cascade.
    Retourne un itérateur de photographies v3 signées, montants EUR individuels
    et tolérance décimale en euros. Les exclusions invalides lèvent ValueError.
    Aucun accès SQL ni écriture de fichier ; mémoire proportionnelle aux clés utiles.
    Les nouvelles clés ODS assimilent NA et vide sans modifier les champs sources.
    """
    identities, accounted, evidence = {}, defaultdict(list), defaultdict(list)
    from reconciliation_contract.sage_inventory import exclusion_policy
    exclusions = exclusion_policy([] if excluded_prefixes is None else excluded_prefixes)["prefixes"]
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
        if any(entry["document"][:3] in exclusions for entry in evidence[key]):
            reasons.append("Type de pièce exclu des contrôles selon la politique de campagne")
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
