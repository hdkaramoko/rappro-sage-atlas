"""Diagnostic ciblé des seules ODA comptabilisées avec tiers Atlas absent."""

from decimal import Decimal
from bisect import bisect_left, bisect_right
from collections import defaultdict

from reconciliation_contract import money, text, year_of


def missing_party(value):
    """Reconnaît uniquement null, vide ou NA pour le contrôle, sans transformer la source."""
    return text(value).upper() in ("", "NA")


def amount_indexes(entries):
    """Indexe une fois les écritures par montant et tiers, en conservant toutes les occurrences."""
    groups = defaultdict(list)
    for entry in entries:
        amount = money(entry.get("amount"))
        if amount is not None:
            groups[None].append((amount, entry))
            groups[text(entry.get("third_party")).upper()].append((amount, entry))
    result = {}
    for key, values in groups.items():
        values.sort(key=lambda pair: pair[0])
        result[key] = ([pair[0] for pair in values], [pair[1] for pair in values])
    return result


def near_entries(index, amount, tolerance):
    """Retourne au plus deux occurrences de même signe dans l'intervalle, sans produit croisé."""
    amounts, rows = index
    matches = []
    for position in range(bisect_left(amounts, amount - tolerance), bisect_right(amounts, amount + tolerance)):
        if amounts[position] * amount >= 0:
            matches.append(rows[position])
            if len(matches) == 2:
                break
    return matches


def oda_diagnostic(identity, atlas, entries, *, amount_field, tolerance):
    """Retourne un diagnostic de pièce ODA ou None si l'exception ne s'applique pas.

    Vérifie projet/exercice/pièce, sommes signées, identités et multiplicité.
    Les tiers renseignés ne sont jamais ignorés. Aucune affectation ni autorisation
    AUTO n'est créée ; une ambiguïté individuelle reste explicite même à total égal.
    """
    if (identity["strategy"] != "STANDARD_BY_DOCUMENT" or not identity["parts"][2].startswith("ODA")
            or not atlas or not any(missing_party(row.get("sage_third_party_code")) for row in atlas)
            or any(row.get("bap_status") != "Comptabilisé" for row in atlas)):
        return None
    reasons = []
    key = tuple(identity["parts"])
    if not all(value not in (None, "") for value in key):
        reasons.append("Projet, exercice ou pièce ODA absent")
    if any((row.get("project_code"), row.get("fiscal_year"), row.get("sage_document_number")) != key for row in atlas):
        reasons.append("Source Atlas hors pièce ODA")
    if any((row.get("project_code"), row.get("fiscal_year"), row.get("document")) != key for row in entries):
        reasons.append("Écriture Sage hors pièce ODA")
    if (any(year_of(row.get("accounting_date")) != row.get("fiscal_year") for row in atlas)
            or any(year_of(row.get("date")) != row.get("fiscal_year") for row in entries)):
        reasons.append("Date ou exercice ODA absent ou incohérent")
    refs = [row.get("ref") for row in entries]
    ids = [row.get("source_id") for row in atlas]
    if (not entries or len(refs) != len(set(refs)) or any(not row.get("identity_complete") for row in entries)
            or len(ids) != len(set(ids)) or not all(ids) or len({row.get("journal") for row in entries}) != 1):
        reasons.append("Identité ou multiplicité ODA ambiguë")
    left = [money(row.get(amount_field)) for row in atlas]
    right = [money(row.get("amount")) for row in entries]
    gap = sum(left, Decimal(0)) - sum(right, Decimal(0)) if all(v is not None for v in left + right) else None
    if gap is None:
        reasons.append("Montant ODA absent ou invalide")
    elif abs(gap) > money(tolerance):
        reasons.append("Écart entre les totaux de la pièce ODA")
    used = set()
    indexed = amount_indexes(entries)
    for row, amount in zip(atlas, left):
        if amount is None:
            continue
        party = None if missing_party(row.get("sage_third_party_code")) else text(row["sage_third_party_code"]).upper()
        matches = near_entries(indexed.get(party, ([], [])), amount, money(tolerance))
        if len(matches) != 1 or matches[0]["ref"] in used:
            reasons.append("Correspondances individuelles ODA non uniques ou tiers renseignés divergents")
        else:
            used.add(matches[0]["ref"])
    if len(atlas) != len(entries):
        reasons.append("Cardinalités ODA différentes : revue individuelle nécessaire")
    return {"message": "Tiers Atlas absent/NA, contrôle sur pièce", "reliable": not reasons,
            "reasons": sorted(set(reasons)), "gap": str(gap) if gap is not None else None,
            "automatic_authorization": False}
