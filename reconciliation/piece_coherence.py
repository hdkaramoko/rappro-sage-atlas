"""Indexe les pièces Atlas envoyées sur SAGE complet, sans filtre de date."""

from collections import defaultdict

from reconciliation import config
from reconciliation.matching.trace import json_value
from reconciliation_contract.piece_coherence import atlas_entry, check_piece, identifier, sage_entry

ATLAS_COLUMNS = ("Id", "Code projet", "N° pièce SAGE", "Date comptable", "Année",
                 "Code tiers SAGE", "N° BAP (SAGE)", "Total charges SAGE (€)", "Statut BAP")
SAGE_COLUMNS = ("Projet", "Numéro pièce", "Date comptable", "Code Tiers - Tiers doc Orig",
                "Référence", "Charges (Dépenses)", "Journal", "N° de ligne comptable",
                "N° de ligne Analytique", "Devise")


def build_piece_checks(atlas, sage):
    options = config.PIECE_COHERENCE
    if (not isinstance(options, dict) or type(options.get("enabled")) is not bool
            or options.get("mode") not in ("DIAGNOSTIC", "ACTIVE")):
        raise ValueError("PIECE_COHERENCE : enabled booléen et mode DIAGNOSTIC ou ACTIVE requis")
    if not options["enabled"]:
        return {}
    groups, entries = defaultdict(list), defaultdict(list)
    for values in atlas.reindex(columns=ATLAS_COLUMNS).itertuples(index=False, name=None):
        raw = json_value(dict(zip(ATLAS_COLUMNS, values)))
        if raw["Statut BAP"] == config.ATLAS_STATUS_SENT_TO_SAGE:
            row = atlas_entry(raw)
            if row["project"] and row["document"]:
                groups[(row["project"], row["document"])].append(row)
    uncertain_projects, uncertain_documents = set(), set()
    for values in sage.reindex(columns=SAGE_COLUMNS).itertuples(index=False, name=None):
        # Éviter de sérialiser toute l'extraction pour les seules pièces utiles.
        raw = dict(zip(SAGE_COLUMNS, values))
        key = (identifier(json_value(raw["Projet"])), identifier(json_value(raw["Numéro pièce"])))
        if key[0] and not key[1]:
            uncertain_projects.add(key[0])
        if key[1] and not key[0]:
            uncertain_documents.add(key[1])
        if key in groups:
            entries[key].append(sage_entry(json_value(raw)))
    reasons = []
    if atlas.attrs.get("load_summary", {}).get("conflicting_ids", 0):
        reasons.append("Conflits d'identifiants Atlas : périmètre non fiable")
    if sage.attrs.get("load_summary", {}).get("invalid_accounting_dates", 0):
        reasons.append("Dates SAGE invalides dans l'extraction : périmètre à vérifier")
    return {key: check_piece(*key, rows, entries[key], scope_reasons=[*reasons, *(
                ["Écritures SAGE sans projet ou pièce : périmètre incomplet"]
                if key[0] in uncertain_projects or key[1] in uncertain_documents else []
            )]) for key, rows in groups.items()}
