"""Recette minimale synthétique : trois ODG à -890 et un BAP avec quatre faux concurrents."""

from pathlib import Path
import sys

import pandas as pd

from reconciliation.exporters.review import export_review_bundle
from reconciliation.matching import MatchingConfig, match_reconciliations
from reconciliation.multiples import build_controls
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage


def generate(folder, *, project_departments=None):
    """Écrit un JSONL fictif de huit lignes par source, sans accès à une base.

    project_departments ajoute facultativement les rattachements de test à
    l'en-tête ; sources, matching et décisions restent identiques.
    """
    left, right = [], []
    for number, amount in enumerate(("-310", "-170", "-410"), 1):
        doc = f"ODG-TEST-{number}"
        left.append({"Id": f"OD{number}", "Code projet": "P", "Année": 2026, "Statut BAP": "Comptabilisé",
            "Code tiers SAGE": "", "Libellé SAGE": "TVA TEST", "Libellé ATLAS": "",
            "Total charges projet (€)": amount, "Total charges SAGE (€)": amount,
            "N° pièce SAGE": doc, "Date comptable": "2026-02-27", "N° BAP (SAGE)": ""})
        right.append({"Projet": "P", "Numéro pièce": doc, "Date comptable": "2026-02-27",
            "Journal": "ODDIV", "N° de ligne comptable": "1", "N° de ligne Analytique": "1",
            "Charges (Dépenses)": amount, "Code Tiers - Tiers doc Orig": "NA", "Libellé pièce": "TVA TEST", "Référence": ""})
    for number in range(5):
        doc = "CIF-TARGET" if number == 0 else f"FAF-ACCOUNTED-{number}"
        left.append({"Id": "BAP-TARGET" if number == 0 else f"C{number}", "Code projet": "P", "Année": 2026,
            "Statut BAP": "Envoyé SAGE" if number == 0 else "Comptabilisé", "Code tiers SAGE": "T",
            "Libellé ATLAS": "LIBELLE ATLAS", "Libellé SAGE": "LIBELLE SAGE",
            "Total charges projet (€)": "782.85", "Total charges SAGE (€)": None if number == 0 else "782.85",
            "N° pièce SAGE": "" if number == 0 else doc,
            "Date comptable": None if number == 0 else "2026-03-31",
            "N° BAP (SAGE)": "BAP-TARGET" if number == 0 else ""})
        right.append({"Projet": "P", "Numéro pièce": doc, "Date comptable": "2026-03-31",
            "Journal": "ACHAT", "N° de ligne comptable": "2", "N° de ligne Analytique": "1",
            "Charges (Dépenses)": "782.85", "Code Tiers - Tiers doc Orig": "T", "Libellé pièce": "COMPTABILITE DIFFERENTE",
            "Référence": "BAP-TARGET" if number == 0 else f"BAP-C{number}"})
    atlas, sage = transform_atlas(pd.DataFrame(left)), transform_sage(pd.DataFrame(right))
    result = match_reconciliations(atlas, sage, MatchingConfig(enable_fuzzy=False, enable_without_label=False))
    return export_review_bundle(atlas, sage, result, Path(folder) / "ods-bap.jsonl", year=2026,
        controls=build_controls(atlas, sage, result), include_sage_inventory=True,
        project_departments=project_departments)


if __name__ == "__main__":
    print(generate(sys.argv[1]))
