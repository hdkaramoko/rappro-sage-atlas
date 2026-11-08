"""Contrat métier pur partagé par le moteur Python et l'application Django.

Aucune dépendance à pandas ou Django : mêmes clés, centimes et diagnostics
à l'export et au contrôle serveur, sans deux interprétations concurrentes.
"""

import hashlib
import json
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

VERSION = 3
STANDARD = "STANDARD_BY_DOCUMENT"
ODS = "ODS_ODG_BY_GROUP"
TOLERANCE = "0.01"
ODS_LABEL_POLICY = "sage-accounted-v1"
EXTRA_INVENTORY = {
    "Code tiers SAGE": "sage_third_party_code",
    "Libellé ATLAS": "atlas_label",
    "Devise": "currency",
}


def text(value):
    """Harmonise Unicode et espaces sans supprimer les zéros initiaux."""
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())


def label(value):
    """Compare les libellés sans casse/accents, sans fuzzy ni mots supprimés."""
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", text(value).casefold())
        if not unicodedata.combining(c)
    )


def digest(value):
    """Identifie un contenu métier indépendamment de l'ordre des clés JSON."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def money(value):
    """Retourne un Decimal fini ; une absence ne vaut jamais zéro."""
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and abs(number) < Decimal("1e16") else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def year_of(value):
    """Extrait l'année d'une date ISO, ou signale son absence par None."""
    try:
        return date.fromisoformat(str(value)[:10]).year
    except (ValueError, TypeError):
        return None


def is_ods(document, journal=""):
    """Reconnaît ODS/ODG par préfixe de pièce ou code journal explicite."""
    return text(document).upper().startswith(("ODS", "ODG")) or text(
        journal
    ).upper() in ("ODS", "ODG")


def atlas_control_label(row):
    """Choisit le libellé du contrôle Atlas sans changer la recherche de propositions.

    Comptabilisé au nouveau format utilise sage_label, même vide. Envoyé SAGE
    conserve atlas_label. L'absence du champ signale un ancien contrat et conserve
    sa règle historique, pour ne pas réinterpréter ses clés et signatures.
    Retourne la valeur source ; aucune conversion, écriture ou repli sur un vide.
    """
    if row.get("bap_status") == "Comptabilisé" and "sage_label" in row:
        return row.get("sage_label")
    return row.get("atlas_label")


def control_identity(row, *, sage=False):
    """Résout la clé standard ou ODS ; les clés incomplètes restent isolées.

    Les ODS comptabilisés du nouveau contrat comparent Libellé SAGE Atlas au
    Libellé pièce Sage. Envoyé SAGE et anciens contrats gardent Libellé ATLAS.
    La sélection du libellé ne change pas la normalisation ni la clé standard.
    """
    project = text(row.get("project_code")).upper()
    year = row.get("fiscal_year")
    document = text(
        row.get("document") if sage else row.get("sage_document_number")
    ).upper()
    ods = is_ods(document, row.get("journal", ""))
    parts = [project, year]
    if ods:
        parts += [
            text(
                row.get("third_party") if sage else row.get("sage_third_party_code")
            ).upper(),
            label(row.get("label") if sage else atlas_control_label(row)),
        ]
    else:
        parts += [document]
    return {"strategy": ODS if ods else STANDARD, "parts": parts}


def entry_from_sage(raw):
    """Décrit une écriture analytique issue d'un dictionnaire source Sage.

    Retourne identité SHA256, champs texte conservant les zéros initiaux et
    charges EUR décimales signées (None si absentes). La valeur décimale
    préservée par le loader prime sur la colonne flottante du matching ; les
    anciens JSONL sans cette valeur suivent la politique v3 historique.
    Aucun effet de bord ; une identité incomplète est explicitement marquée.
    """
    amount = money(raw.get("_charges_decimal", raw.get("Charges (Dépenses)")))
    row = {
        "project_code": text(raw.get("Projet")).upper(),
        "document": text(raw.get("Numéro pièce")).upper(),
        "date": str(raw.get("Date comptable") or "")[:10],
        "journal": text(raw.get("Journal")).upper(),
        "line": text(raw.get("N° de ligne comptable")),
        "analytic_line": text(raw.get("N° de ligne Analytique")),
        "third_party": text(raw.get("Code Tiers - Tiers doc Orig")).upper(),
        "label": text(raw.get("Libellé pièce")),
        "original_label": str(raw.get("Libellé pièce") or ""),
        "currency": text(raw.get("Devise")).upper(),
        "amount": str(amount) if amount is not None else None,
    }
    row["fiscal_year"] = year_of(row["date"])
    identity = [
        row[k]
        for k in (
            "project_code",
            "fiscal_year",
            "document",
            "journal",
            "line",
            "analytic_line",
        )
    ]
    row["ref"] = digest(identity)
    row["identity_complete"] = all(v not in (None, "") for v in identity)
    return row


def compare(atlas_amounts, sage_amounts, *, reasons=(), tolerance=TOLERANCE):
    """Compare des sommes complètes ; avoirs homogènes comparés en valeur absolue.

    Un mélange de signes rend le diagnostic indéterminé : compenser une charge
    par un avoir pourrait masquer un multiple. Aucun sous-total n'est présenté
    comme un total complet en présence d'un montant invalide.
    """
    left, right = [money(v) for v in atlas_amounts], [money(v) for v in sage_amounts]
    why = list(reasons)
    if any(v is None for v in left + right):
        why.append("Montant absent ou invalide : somme incomplète")
    if not right:
        why.append("Aucune écriture SAGE résolue")
    valid = [v for v in left + right if v is not None and v != 0]
    if any(v < 0 for v in valid) and any(v > 0 for v in valid):
        why.append("Signes mixtes / compensation charge-avoir à examiner")
    a = sum(left, Decimal(0)) if all(v is not None for v in left) else None
    s = sum(right, Decimal(0)) if right and all(v is not None for v in right) else None
    gap = abs(a) - abs(s) if a is not None and s is not None else None
    status = (
        "UNKNOWN"
        if why
        else "EXCESS"
        if gap > Decimal(tolerance)
        else "SHORTFALL"
        if gap < -Decimal(tolerance)
        else "BALANCED"
    )
    return {
        "atlas_total": str(a) if a is not None else None,
        "sage_total": str(s) if s is not None else None,
        "gap": str(gap) if gap is not None else None,
        "status": status,
        "reasons": sorted(set(why)),
    }


def snapshot(
    identity, atlas, entries, *, amount_field, tolerance=TOLERANCE, reasons=()
):
    """Photographie les preuves et leur diagnostic, avec signature métier stable.

    Un nouveau source Comptabilisé ODS sans Libellé SAGE explicite reste à revoir,
    même si Libellé ATLAS est renseigné. Les anciens snapshots restent compatibles.
    """
    why = list(reasons)
    if not all(v not in (None, "") for v in identity["parts"]):
        why.append("Clé de résolution incomplète")
    if amount_field not in ("total_sage_charges", "total_project_charges"):
        why.append("Sémantique du montant Atlas non confirmée")
    for row in atlas:
        if (identity["strategy"] == ODS and row.get("bap_status") == "Comptabilisé"
                and "sage_label" in row and not label(row.get("sage_label"))):
            why.append("Libellé SAGE Atlas absent pour le contrôle ODS/ODG")
        if not year_of(row.get("accounting_date")) or year_of(
            row.get("accounting_date")
        ) != row.get("fiscal_year"):
            why.append("Date Atlas absente ou exercice comptable différent")
    refs = set()
    unreliable_identity = False
    for row in entries:
        if row["ref"] in refs or not row["identity_complete"]:
            why.append("Identifiant d'écriture SAGE absent ou non unique")
            unreliable_identity = True
        if not year_of(row.get("date")) or year_of(row.get("date")) != row.get(
            "fiscal_year"
        ):
            why.append("Date SAGE absente ou exercice incohérent")
        refs.add(row["ref"])
    if identity["strategy"] == STANDARD and len({r["journal"] for r in entries}) > 1:
        why.append("Pièce partagée entre plusieurs journaux")
    diagnosis = compare(
        [r.get(amount_field) for r in atlas],
        [r["amount"] for r in entries],
        reasons=why,
        tolerance=tolerance,
    )
    if unreliable_identity:
        diagnosis.update(sage_total=None, gap=None)
    data = {
        "identity": identity,
        "atlas": sorted(atlas, key=lambda r: digest(r)),
        "entries": sorted(entries, key=lambda r: (r["ref"], digest(r))),
        "amount_field": amount_field,
        "amount_currency": "EUR",
        "tolerance": tolerance,
        "atlas_count": len(atlas),
        "sage_count": len(entries),
        **diagnosis,
    }
    data["signature"] = digest(data)
    data["key"] = digest(identity)
    return data
