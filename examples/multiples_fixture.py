"""Produit de petits fichiers fictifs pour tester moteur → campagne → application."""

import sys
from pathlib import Path

import pandas as pd

from reconciliation.main import main


def generate(folder):
    """Écrit deux propositions distinctes partageant une pièce et un existant Atlas."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    atlas = []
    for identifier, status, amount, bap in [
        ("C", "Comptabilisé", 40, ""),
        ("A", "Envoyé SAGE", 60, "B1"),
        ("B", "Envoyé SAGE", 60, "B2"),
    ]:
        atlas.append(
            {
                "Id": identifier,
                "Code projet": "P",
                "Année": 2026,
                "Statut BAP": status,
                "Total charges projet (€)": amount,
                "Total charges SAGE (€)": amount if identifier == "C" else None,
                "N° pièce SAGE": "D" if identifier == "C" else "",
                "Date comptable": "01/01/2026" if identifier == "C" else "",
                "Libellé ATLAS": "Mission",
                "Code tiers SAGE": "001",
                "N° BAP (SAGE)": bap,
                "Devise": "EUR",
            }
        )
    sage = [
        {
            "Projet": "P",
            "Numéro pièce": "D",
            "Date comptable": "01/01/2026",
            "Journal": "ACH",
            "N° de ligne comptable": f"00{i}",
            "N° de ligne Analytique": "01",
            "Charges (Dépenses)": 60,
            "Devise": "EUR",
            "Code Tiers - Tiers doc Orig": "001",
            "Libellé pièce": "Mission",
            "Référence": f"B{i}",
        }
        for i in (1, 2)
    ]
    pd.DataFrame(atlas).to_excel(folder / "atlas.xlsx", index=False)
    pd.DataFrame(sage).to_csv(folder / "sage.csv", index=False, sep=";")
    return main(
        [
            "--atlas",
            str(folder / "atlas.xlsx"),
            "--sage",
            str(folder / "sage.csv"),
            "--year",
            "2026",
            "--accounted-amount-field",
            "total_sage_charges",
            "--review-output",
            str(folder / "campaign.jsonl"),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(generate(sys.argv[1]))
