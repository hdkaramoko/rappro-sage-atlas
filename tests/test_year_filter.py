"""L'année limite Atlas et les dates comptables SAGE avant le rapprochement."""

import json

import pandas as pd
import pytest

from reconciliation.loaders.atlas import AtlasLoaderError, load_atlas
from reconciliation.loaders.sage import SageLoaderError, load_sage
from reconciliation.main import main


def files(tmp_path):
    atlas = tmp_path / "atlas.xlsx"
    with pd.ExcelWriter(atlas) as writer:
        pd.DataFrame([
            {"Id": "A", "Code projet": "P", "Année": 2025, "Statut BAP": "Envoyé SAGE"},
            {"Id": "A", "Code projet": "P", "Année": 2026, "Statut BAP": "Envoyé SAGE"},
            {"Id": "B", "Code projet": "P", "Année": 2026, "Statut BAP": "Comptabilisé"},
        ]).to_excel(writer, index=False, sheet_name="Données")
        pd.DataFrame([{"Id": "C", "Code projet": "P", "Année": 2024}]).to_excel(writer, index=False, sheet_name="Historique")
    sage = tmp_path / "sage.csv"
    pd.DataFrame([
        {"Projet": "P", "Numéro pièce": "D25", "Date comptable": "31/12/2025"},
        {"Projet": "P", "Numéro pièce": "D26", "Date comptable": "01/01/2026"},
        {"Projet": "P", "Numéro pièce": "FIN26", "Date comptable": "31/12/2026"},
        {"Projet": "P", "Numéro pièce": "D27", "Date comptable": "01/01/2027"},
        {"Projet": "P", "Numéro pièce": "INVALIDE", "Date comptable": "inconnue"},
    ]).to_csv(sage, index=False, sep=";")
    return atlas, sage


def test_atlas_filter_precedes_deduplication_and_keeps_all_statuses(tmp_path):
    atlas, _ = files(tmp_path)
    rows = load_atlas(atlas, year=2026)
    assert list(rows["Id"]) == ["A", "B"]
    assert rows["Année"].eq(2026).all()
    assert rows.attrs["load_summary"]["rows_excluded_by_year"] == 2
    assert rows.attrs["load_summary"]["duplicates_removed"] == 0
    assert len(load_atlas(atlas)) == 3


def test_sage_filter_uses_accounting_date_and_excludes_invalid_dates(tmp_path):
    _, sage = files(tmp_path)
    rows = load_sage(sage, year=2026)
    assert list(rows["Numéro pièce"]) == ["D26", "FIN26"]
    assert rows.attrs["load_summary"]["rows_excluded_by_year"] == 3
    assert rows.attrs["load_summary"]["invalid_accounting_dates"] == 1


def test_empty_year_fails_before_publishing_outputs(tmp_path):
    atlas, sage = files(tmp_path)
    with pytest.raises(AtlasLoaderError, match="Aucune ligne Atlas"):
        load_atlas(atlas, year=2023)
    with pytest.raises(SageLoaderError, match="Aucune ligne SAGE"):
        load_sage(sage, year=2023)
    output = tmp_path / "empty.jsonl"
    assert main(["--atlas", str(atlas), "--sage", str(sage), "--year", "2023", "--review-output", str(output)]) == 1
    assert not output.exists()


def test_cli_publishes_only_requested_year_and_records_it(tmp_path):
    atlas, sage = files(tmp_path)
    output = tmp_path / "campaign.jsonl"
    assert main(["--atlas", str(atlas), "--sage", str(sage), "--year", "2026", "--review-output", str(output)]) == 0
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert records[0]["year"] == 2026
    assert records[-1]["inventory_count"] == 2
    assert [row["atlas"]["Id"] for row in records if row.get("type") == "inventory"] == ["A", "B"]
    assert records[-1]["complete"] == 1


def test_missing_year_column_and_invalid_argument_are_rejected(tmp_path):
    atlas = tmp_path / "missing.xlsx"
    pd.DataFrame([{"Id": "A", "Code projet": "P"}]).to_excel(atlas, index=False)
    with pytest.raises(AtlasLoaderError, match="colonne Année"):
        load_atlas(atlas, year=2026)
    with pytest.raises(SystemExit):
        main(["--atlas", str(atlas), "--sage", "not-needed.csv", "--year", "999"])
