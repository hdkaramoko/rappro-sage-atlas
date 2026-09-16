"""Crée un classeur de démonstration synthétique : uv run python -m examples.demo_export."""

from pathlib import Path

import pandas as pd

from reconciliation.exporters.excel import export_reconciliation
from reconciliation.matching import match_reconciliations
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage


def main():
    atlas_rows, sage_rows = [], []
    for number, case in enumerate(("EXACT", "MONTANT", "FUZZY", "AMBIGU", "ABSENT", "HORS", "PREUVE"), 1):
        atlas = {
            "Id": f"{number:04d}", "Code projet": "DEMO-2026", "Libellé projet": "Projet de démonstration",
            "Année": 2026, "Activité": case, "Code ligne budgétaire": "0010",
            "Libellé ligne budgetaire": "Prestations", "Libellé ATLAS": "FACTURE CONSULTANT DUPONT JANVIER",
            "Nature de dépense (ATLAS)": "Honoraires", "Code tiers SAGE": "T001", "Nom du tiers": "Tiers fictif",
            "N° BAP (SAGE)": f"BAP-{number:04d}", "Statut BAP": "Envoyé SAGE",
            "Lieu de paiement": "Paris", "Moyen de paiement": "Virement",
            "Date comptable": None, "N° pièce SAGE": None, "Total charges projet (€)": 1000.,
            "Total charges SAGE (€)": None,
        }
        sage = {"Projet": atlas["Code projet"], "Libellé pièce": atlas["Libellé ATLAS"],
                "Code Tiers - Tiers doc Orig": "T001", "Référence": atlas["N° BAP (SAGE)"],
                "Charges (Dépenses)": 1000., "Numéro pièce": f"SAGE-{number:04d}",
                "Date comptable": pd.Timestamp("2026-09-01")}
        if case == "HORS":
            atlas["Statut BAP"] = "Brouillon"
        elif case == "PREUVE":
            atlas.update({"Date comptable": pd.Timestamp("2026-08-31"), "N° pièce SAGE": "DEJA-PRESENTE", "Total charges SAGE (€)": 1000.})
        elif case == "FUZZY":
            sage["Libellé pièce"] = "JANVIER DUPONT FACTURE CONSULTANT"
        elif case == "MONTANT":
            sage["Charges (Dépenses)"] = 500.
            sage_rows.append(sage.copy())
        elif case == "AMBIGU":
            sage["Libellé pièce"] = "AUTRE LIBELLE"
            sage_rows.append({**sage, "Libellé pièce": "LIBELLE DIFFERENT", "Numéro pièce": "SAGE-ALTERNATIVE"})
        atlas_rows.append(atlas)
        if case not in ("HORS", "ABSENT", "PREUVE"):
            sage_rows.append(sage)
    atlas = transform_atlas(pd.DataFrame(atlas_rows))
    sage = transform_sage(pd.DataFrame(sage_rows))
    result = match_reconciliations(atlas, sage, collect_trace=True)
    path = export_reconciliation(atlas, result, Path("data") / "exemple_rapprochement.xlsx")
    print(f"Démonstration synthétique : {path}")


if __name__ == "__main__":
    main()
