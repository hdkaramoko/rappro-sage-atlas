"""Recette fictive des deux libellés Atlas, avec contrôle ODS et recherche Envoyé."""

import sys
from pathlib import Path
import pandas as pd
from reconciliation.main import main


def generate(folder):
    """Écrit trois sources Atlas fictives et lance le vrai moteur annuel.

    C est un ODS comptabilisé à libellés différents, M un ODS sans libellé Sage,
    S une recherche Envoyé Exact avec un libellé Sage volontairement trompeur.
    Retourne le code CLI ; aucune base applicative ni source métier n'est utilisée.
    """
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    atlas = []
    sage = []
    for identifier, party, amount, document, atlas_label, sage_label in [
        ("C", "T", "100", "ODS-ATLAS", "Texte Atlas différent", "Réaffect salaires 08/26"),
        ("M", "M", "200", "ODS-MISSING", "Texte seul disponible", None),
        ("S", "S", "50", "", "Mission Recherche", "Ancien texte à ignorer")]:
        sent = identifier == "S"
        atlas.append({"Id": identifier, "Code projet": "P", "Année": 2026,
            "Statut BAP": "Envoyé SAGE" if sent else "Comptabilisé", "Code tiers SAGE": party,
            "Libellé ATLAS": atlas_label, "Libellé SAGE": sage_label, "N° BAP (SAGE)": "BAP-S" if sent else "",
            "Total charges projet (€)": amount, "Total charges SAGE (€)": None if sent else amount,
            "N° pièce SAGE": document, "Date comptable": "" if sent else "01/01/2026", "Devise": "EUR"})
        sage.append({"Projet": "P", "Numéro pièce": {"C": "ODG-SAGE", "M": "ODG-MISSING", "S": "FAC-S"}[identifier],
            "Date comptable": "01/01/2026", "Journal": "ACH", "N° de ligne comptable": identifier,
            "N° de ligne Analytique": "1", "Code Tiers - Tiers doc Orig": party,
            "Libellé pièce": atlas_label if sent or identifier == "M" else sage_label,
            "Référence": "BAP-S" if sent else "", "Charges (Dépenses)": amount, "Devise": "EUR"})
    pd.DataFrame(atlas).to_excel(root / "atlas.xlsx", index=False)
    pd.DataFrame(sage).to_csv(root / "sage.csv", index=False, sep=";")
    return main(["--atlas", str(root / "atlas.xlsx"), "--sage", str(root / "sage.csv"), "--year", "2026",
                 "--campaign-name", "Recette libellés ODS", "--review-output", str(root / "campaign.jsonl")])


if __name__ == "__main__":
    raise SystemExit(generate(sys.argv[1]))
