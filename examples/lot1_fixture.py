"""Produit une campagne lot 1 entièrement fictive pour la recette automatique."""

import sys
from pathlib import Path

import pandas as pd

from reconciliation.main import main


def generate(folder: str) -> int:
    """Écrit dans `folder` deux sources et le JSONL du cas 6000 + 4000 = 10000.

    Ajoute une pièce sans Atlas et un ODS avec Libellé ATLAS vide mais Libellé SAGE
    renseigné, afin d'exercer le choix du libellé comptable sans changer le matching.
    Retourne le code CLI ; seuls ces fichiers synthétiques sont créés.
    """
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    atlas = [
        {"Id": "C", "Code projet": "P", "Année": 2026, "Statut BAP": "Comptabilisé",
         "Total charges projet (€)": "6000", "Total charges SAGE (€)": "6000", "N° pièce SAGE": "FAC123",
         "Date comptable": "01/01/2026", "Code tiers SAGE": "001", "Libellé ATLAS": "Mission", "N° BAP (SAGE)": "B1", "Devise": "EUR"},
        {"Id": "S", "Code projet": "P", "Année": 2026, "Statut BAP": "Envoyé SAGE",
         "Total charges projet (€)": "4000", "Total charges SAGE (€)": None, "N° pièce SAGE": "",
         "Date comptable": "", "Code tiers SAGE": "001", "Libellé ATLAS": "Mission", "N° BAP (SAGE)": "B2", "Devise": "EUR"},
        {"Id": "O", "Code projet": "P", "Année": 2026, "Statut BAP": "Comptabilisé",
         "Total charges projet (€)": "100", "Total charges SAGE (€)": "100", "N° pièce SAGE": "ODS-ATLAS",
         "Date comptable": "01/01/2026", "Code tiers SAGE": "002", "Libellé ATLAS": "", "N° BAP (SAGE)": "", "Devise": "EUR"},
    ]
    atlas[-1]["Libellé SAGE"] = "ODG Recette"
    sage = []
    for line, document, amount, party, label, bap in [
        ("001", "FAC123", "6000", "001", "Mission", "B1"),
        ("002", "FAC123", "4000", "001", "Mission", "B2"),
        ("003", "FAC999", "50", "003", "Sans Atlas", "B3"),
        ("004", "ODG-SAGE", "100", "002", "ODG Recette", ""),
    ]:
        sage.append({"Projet": "P", "Numéro pièce": document, "Date comptable": "01/01/2026",
                     "Journal": "ACH", "N° de ligne comptable": line, "N° de ligne Analytique": "01",
                     "Charges (Dépenses)": amount, "Code Tiers - Tiers doc Orig": party,
                     "Libellé pièce": label, "Référence": bap, "Devise": "EUR"})
    pd.DataFrame(atlas).to_excel(root / "atlas.xlsx", index=False)
    pd.DataFrame(sage).to_csv(root / "sage.csv", index=False, sep=";")
    return main(["--atlas", str(root / "atlas.xlsx"), "--sage", str(root / "sage.csv"),
                 "--year", "2026", "--review-output", str(root / "campaign.jsonl")])


if __name__ == "__main__":
    raise SystemExit(generate(sys.argv[1]))
