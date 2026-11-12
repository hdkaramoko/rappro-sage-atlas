"""Petite campagne synthétique de recette du seuil résiduel et des références BAP."""

import sys
from pathlib import Path
import pandas as pd

from reconciliation.matching import match_reconciliations
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage
from reconciliation.exporters.review import export_review_bundle
from reconciliation.multiples import build_controls


def frames():
    """Retourne les DataFrames fictifs : BAP à 0,04, individuel à 0,0116 et cumul refusé.

    Ajoute une ligne Comptabilisé dont BAP et libellés Atlas/Sage sont distincts
    pour contrôler leur origine à l'écran. Aucun accès à des données réelles.
    """
    atlas, sage = [], []
    for bap, rows, amounts in [
        ("BAP-A", [("A1", "100.02"), ("A2", "200.02")], ["100", "200"]),
        ("BAP-I", [("I", "362.2616")], ["362.25", "50"]),
        ("BAP-LIMIT", [("L", "500.0500")], ["500", "50"]),
        ("BAP-OVER", [("O", "700.0501")], ["700", "50"]),
        ("BAP-DRIFT", [("D1", "1000.03"), ("D2", "2000.03")], ["1000", "2000"]),
        ("BAP-ATLAS-C", [("C", "1")], ["1"])]:
        document = "COMPTA" if bap.endswith("-C") else "FAC-" + bap
        for identifier, amount in rows:
            atlas.append({"Id": identifier, "Code projet": "P", "Année": 2026,
                "Statut BAP": "Comptabilisé" if identifier == "C" else "Envoyé SAGE",
                "N° BAP (SAGE)": bap, "Code tiers SAGE": "T", "Libellé ATLAS": "LIBELLE_ATLAS_NON_UTILISE" if identifier == "C" else identifier,
                "Libellé SAGE": "SAGE_DANS_ATLAS" if identifier == "C" else "",
                "Total charges projet (€)": amount, "Total charges SAGE (€)": amount if identifier == "C" else None,
                "N° pièce SAGE": document if identifier == "C" else "",
                "Date comptable": pd.Timestamp("2026-01-01") if identifier == "C" else None, "Devise": "EUR - Euro"})
        for number, amount in enumerate(amounts, 1):
            sage.append({"Projet": "P", "Numéro pièce": document, "Date comptable": pd.Timestamp("2026-01-01"),
                "Journal": "ACH", "N° de ligne comptable": str(number), "N° de ligne Analytique": "1",
                "Code Tiers - Tiers doc Orig": "T", "Référence": "BAP-SAGE-C" if document == "COMPTA" else bap,
                "Libellé pièce": "SAGE_EXTRACTION" if document == "COMPTA" else "Libellé Sage commun",
                "Charges (Dépenses)": amount, "Devise": "EUR"})
    return transform_atlas(pd.DataFrame(atlas)), transform_sage(pd.DataFrame(sage))


def generate(folder):
    """Exporte uniquement la recette fictive dans folder, sans import ni base utilisateur.

    Retourne le Path du JSONL v3 avec preuves exactes et politique ciblée ;
    les erreurs des transformations/export sont propagées.
    """
    atlas, sage = frames()
    result = match_reconciliations(atlas, sage)
    return export_review_bundle(atlas, sage, result, Path(folder) / "volet-a.jsonl",
        controls=build_controls(atlas, sage, result), include_sage_inventory=True, year=2026)


if __name__ == "__main__":
    print(generate(sys.argv[1]))
