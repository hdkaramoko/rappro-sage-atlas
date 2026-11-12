"""Jeu témoin reproductible du BAP et du résiduel, sans extraction réelle."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage
from reconciliation.matching import match_reconciliations, MatchingConfig
from reconciliation.exporters.review import export_review_bundle
from reconciliation.multiples import build_controls
from reconciliation import config


def frames():
    """Retourne deux DataFrames fictifs couvrant les trois règles et une ambiguïté.

    Toutes les charges sont en EUR, les identités comptables distinctes. Aucune
    lecture de fichier privé, mutation de base ou modification d'une campagne.
    """
    atlas, sage = [], []
    scenarios = [
        ("BAPPJT260402077", [("1681313", "ERf Solde perdiem", 660.06), ("1681314", "Frais reel mission", 644.85)], [660.06, 644.85], "ERf Solde"),
        ("B2", [("W", "Inutilisable", 100)], [100], "Autre texte"),
        ("B3", [("I", "Frais individuel", 600)], [600, 50], "Autre dépense"),
        ("B4", [("R1", "Répété un", 200), ("R2", "Répété deux", 200)], [200, 200], "Écritures répétées")]
    for number, (bap, sources, amounts, label) in enumerate(scenarios, 1):
        for identifier, description, amount in sources:
            atlas.append({"Id": identifier, "Code projet": "17GEF0C086", "Année": 2026,
                "Code tiers SAGE": "M81412", "N° BAP (SAGE)": bap, "Libellé ATLAS": description,
                "Statut BAP": "Envoyé SAGE", "Total charges projet (€)": amount, "Devise": "EUR - Euro"})
        for line, amount in enumerate(amounts, 2):
            sage.append({"Projet": "17GEF0C086", "Numéro pièce": "CIF0126040938" if number == 1 else f"FAC{number}",
                "Date comptable": pd.Timestamp("2026-04-20"), "Journal": "ACHCI", "N° de ligne comptable": str(line),
                "N° de ligne Analytique": "1", "Code Tiers - Tiers doc Orig": "M81412", "Référence": bap,
                "Libellé pièce": label, "Charges (Dépenses)": amount, "Devise": "EUR"})
    return transform_atlas(pd.DataFrame(atlas)), transform_sage(pd.DataFrame(sage))


def generate(folder):
    """Écrit les JSONL avant/après et retourne leurs métriques mesurées.

    `folder` reçoit seulement ce jeu fictif. Les autorisations comptées sont celles
    de l'export ; les tests Django vérifient ensuite les réservations effectives.
    ValueError/OSError des exporteurs sont propagées ; aucun accès SQL.
    """
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    atlas, sage = frames()
    summary = {}
    for name, enabled in (("before", False), ("after", True)):
        result = match_reconciliations(atlas, sage, MatchingConfig(enable_residual=enabled), collect_trace=True)
        activation = {**config.AUTO_VALIDATION, "statuses": [rule for rule in config.AUTO_VALIDATION["statuses"]
            if enabled or rule not in ("MATCH_WITHOUT_LABEL", "MATCH_BAP", "MATCH_INDIVIDUAL")]}
        with patch.object(config, "AUTO_VALIDATION", activation):
            path = export_review_bundle(atlas, sage, result, root / f"{name}.jsonl",
                controls=build_controls(atlas, sage, result), include_sage_inventory=True, year=2026)
        proposals = [r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r.get("type") == "proposal"]
        summary[name] = {"rules": result.attrs["matching_summary"], "groups": len(proposals),
            "atlas_lines": sum(len(p["atlas"]) for p in proposals),
            "auto_lines": sum(len(p["atlas"]) for p in proposals if p.get("auto_validation")),
            "manual_lines": sum(len(p["atlas"]) for p in proposals if not p.get("auto_validation"))}
    (root / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(generate(sys.argv[1]), ensure_ascii=True))
