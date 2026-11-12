"""Sources fictives pour la recette moteur → JSONL v3 → nouvelle campagne Django."""

import sys
from pathlib import Path
import pandas as pd
from reconciliation.main import main


def generate(folder):
    """Écrit les sources synthétiques A/B puis exécute le vrai moteur annuel.

    `folder` reçoit atlas.xlsx, sage.csv et campaign.jsonl. Les identifiants des
    cas reproduisent la recette mais toutes les données sont fictives. Retourne
    le code CLI. Aucune connexion Django ni import d'une campagne existante.
    """
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    atlas, sage = [], []
    for source, amount, document, reference, number in [
        ("1903381", "8820", "FAF0126101276", "BAPPJT261002716", "1"),
        ("1559564", "652.40", "CIF0126010016", "EXACT-BAP", "2"),
        ("1559565", "36.48", "CIF0126010016", "EXACT-BAP", "3")]:
        confirmed = source == "1903381"
        atlas.append({"Id": source, "Code projet": "P", "Année": 2026, "Statut BAP": "Envoyé SAGE",
            "Libellé ATLAS": "Mission Confirmé" if confirmed else "Mission Exact",
            "Code tiers SAGE": "T", "N° BAP (SAGE)": reference, "Devise": "EUR",
            "Total charges projet (€)": amount, "Total charges SAGE (€)": amount if confirmed else None,
            "N° pièce SAGE": document if confirmed else "", "Date comptable": "16/10/2026" if confirmed else ""})
        sage.append({"Projet": "P", "Numéro pièce": document, "Date comptable": "16/10/2026",
            "Journal": "ACHAT", "N° de ligne comptable": number, "N° de ligne Analytique": "1",
            "Charges (Dépenses)": amount, "Code Tiers - Tiers doc Orig": "T", "Devise": "EUR",
            "Libellé pièce": "Mission Confirmé" if confirmed else "Mission Exact",
            "Référence": reference + "01042026" if confirmed else reference})
    pd.DataFrame(atlas).to_excel(root / "atlas.xlsx", index=False)
    pd.DataFrame(sage).to_csv(root / "sage.csv", index=False, sep=";")
    return main(["--atlas", str(root / "atlas.xlsx"), "--sage", str(root / "sage.csv"), "--year", "2026",
                 "--campaign-name", "Recette Confirmé Exact v2", "--review-output", str(root / "campaign.jsonl")])


if __name__ == "__main__":
    raise SystemExit(generate(sys.argv[1]))
