"""Diagnostic collectif signé, indépendant des décisions et des contrôles multiples."""

from collections import defaultdict
from decimal import Decimal

from . import digest, entry_from_sage, money, text, year_of

VERSION = 1
TOLERANCE = Decimal("0.01")


def identifier(value):
    return text(value).upper()


def atlas_entry(raw):
    return {
        "source_id": text(raw.get("Id")),
        "project": identifier(raw.get("Code projet")),
        "document": identifier(raw.get("N° pièce SAGE")),
        "date": str(raw.get("Date comptable") or "")[:10],
        "year": raw.get("Année"),
        "third_party": identifier(raw.get("Code tiers SAGE")),
        "bap": identifier(raw.get("N° BAP (SAGE)")),
        "amount": str(money(raw.get("Total charges SAGE (€)")))
        if money(raw.get("Total charges SAGE (€)")) is not None else None,
    }


def sage_entry(raw):
    entry = entry_from_sage(raw)
    return {
        "project": entry["project_code"], "document": entry["document"],
        "date": entry["date"], "year": entry["fiscal_year"],
        "third_party": entry["third_party"], "bap": identifier(raw.get("Référence")),
        "amount": entry["amount"], "ref": entry["ref"],
        "identity_complete": entry["identity_complete"], "journal": entry["journal"],
    }


def check_piece(project, document, atlas, sage, *, scope_reasons=()):
    """Compare les sommes signées puis les multisets tiers/BAP/montants.

    Les montants ne sont ni arrondis ni convertis en valeurs absolues. Trier
    chaque multiset fournit un appariement bijectif, sans réutiliser d'écriture.
    """
    atlas = sorted(atlas, key=digest)
    sage = sorted(sage, key=digest)
    a = [money(r["amount"]) for r in atlas]
    s = [money(r["amount"]) for r in sage]
    at = sum(a, Decimal(0)) if a and all(v is not None for v in a) else None
    st = sum(s, Decimal(0)) if all(v is not None for v in s) else None
    gap = at - st if at is not None and st is not None else None
    reasons = list(scope_reasons)
    missing = not project or not document or not atlas or at is None or st is None
    if missing:
        reasons.append("Clé ou montant manquant : contrôle global incomplet")
    years = {r["year"] for r in atlas + sage}
    if None in years or len(years) != 1 or any(year_of(r["date"]) != r["year"] for r in atlas + sage):
        reasons.append("Exercice absent, différent ou incohérent avec les dates comptables")
    status, individual = "NOT_CHECKED", "NOT_CHECKED"
    if not reasons:
        if not sage:
            status = "PIECE_MISMATCH"
            reasons.append("Pièce absente de l'extraction SAGE")
        elif abs(gap) > TOLERANCE:
            status = "PIECE_MISMATCH"
            reasons.append("Écart entre les totaux signés Atlas et SAGE supérieur à 0,01 €")
        else:
            unknown = any(not r["third_party"] or not r["bap"] for r in atlas + sage)
            refs = [r["ref"] for r in sage]
            if unknown:
                reasons.append("Tiers ou BAP manquant : correspondances individuelles incertaines")
            if len(refs) != len(set(refs)) or any(not r["identity_complete"] for r in sage):
                reasons.append("Identité des écritures SAGE absente ou dupliquée")
            if len({r["source_id"] for r in atlas}) != len(atlas) or any(not r["source_id"] for r in atlas):
                reasons.append("Identité des lignes Atlas absente ou dupliquée")
            if len({r["journal"] for r in sage}) != 1:
                reasons.append("Pièce présente dans plusieurs journaux comptables")
            if reasons:
                status, individual = "PIECE_AMBIGUOUS", "INSUFFICIENT"
            else:
                left, right = defaultdict(list), defaultdict(list)
                for row in atlas:
                    left[(row["third_party"], row["bap"])].append(money(row["amount"]))
                for row in sage:
                    right[(row["third_party"], row["bap"])].append(money(row["amount"]))
                coherent = left.keys() == right.keys() and all(
                    len(left[key]) == len(right[key]) and all(
                        abs(x - y) <= TOLERANCE and not (x * y < 0)
                        for x, y in zip(sorted(left[key]), sorted(right[key]))
                    ) for key in left
                )
                status = "PIECE_RECONCILED" if coherent else "PIECE_MISMATCH"
                individual = "MATCHED" if coherent else "MISMATCH"
                if not coherent:
                    reasons.append("Tiers, BAP, montants signés ou multiplicités différents")
    payload = {
        "version": VERSION, "mode": "DIAGNOSTIC", "project": project, "document": document,
        "status": status, "individual_status": individual,
        "atlas_total": str(at) if at is not None else None,
        "sage_total": str(st) if st is not None else None,
        "gap": str(gap) if gap is not None else None, "tolerance": str(TOLERANCE),
        "atlas_count": len(atlas), "sage_count": len(sage),
        "reasons": sorted(set(reasons)), "scope_reasons": sorted(set(scope_reasons)),
        "atlas": atlas, "sage": sage,
    }
    return {**payload, "signature": digest(payload)}


def validate_check(data):
    """Recalcule le contrat à l'import ; un diagnostic n'est jamais une autorisation."""
    if not isinstance(data, dict) or data != check_piece(
        data["project"], data["document"], data["atlas"], data["sage"],
        scope_reasons=data["scope_reasons"],
    ):
        raise ValueError("Contrôle de cohérence altéré ou version non prise en charge")
    if any((r["project"], r["document"]) != (data["project"], data["document"])
           for r in data["atlas"] + data["sage"]):
        raise ValueError("Écriture hors du périmètre de la pièce")
    return data
