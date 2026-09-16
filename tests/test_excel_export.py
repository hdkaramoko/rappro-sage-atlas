"""Lecture réelle des classeurs pour vérifier restitution, types et provenance."""

import pandas as pd
import pytest
from openpyxl import load_workbook

from matching_helpers import frames, atlas_row, sage_row
from reconciliation.matching import match_reconciliations
from reconciliation.exporters.excel import export_reconciliation, ExportError, canonical_atlas
from reconciliation.exporters.schema import ATLAS_EXPORT_COLUMNS


def workbook_for(tmp_path, atlas=None, sage=None):
    a, s = frames(atlas, sage)
    a.index = [7] * len(a)
    result = match_reconciliations(a, s, collect_trace=True)
    path = export_reconciliation(a, result, tmp_path / "report.xlsx")
    return load_workbook(path), a, result


def records(sheet):
    values = list(sheet.values)
    return [dict(zip(values[0], row)) for row in values[1:]]


def test_workbook_source_rows_order_and_group_amounts(tmp_path):
    a = [atlas_row(Id="001", **{"Total charges projet (€)": 500, "Libellé ligne budgetaire": "Budget"}),
         atlas_row(Id="002", **{"Total charges projet (€)": 500}),
         atlas_row(Id="003", **{"Statut BAP": "Comptabilisé"})]
    wb, atlas, result = workbook_for(tmp_path, a)
    assert wb.sheetnames == ["Résultats", "Tentatives", "Synthèse"]
    sheet = wb["Résultats"]
    assert tuple(next(sheet.values))[:19] == ATLAS_EXPORT_COLUMNS
    rows = records(sheet)
    assert [r["Id"] for r in rows] == ["001", "002", "003"]
    assert rows[0]["Groupe Atlas"] == rows[1]["Groupe Atlas"]
    assert rows[0]["Total charges projet (€)"] == 500
    assert rows[0]["Montant Sage proposé du groupe (€) — non additionnable"] == 1000
    assert rows[0]["Total charges SAGE (€)"] is None
    assert rows[0]["Libellé ligne budgétaire"] == "Budget"
    assert rows[2]["Statut du rapprochement"] == "HORS_PERIMETRE"
    assert rows[2]["Statut BAP"] == "Comptabilisé"
    assert sheet.freeze_panes == "A2" and sheet.auto_filter.ref.endswith("4")
    assert sheet["A2"].data_type == "s"
    assert records(wb["Tentatives"])[-1]["Étape"] == "DECISION_FINALE"
    wb.close()


def test_text_is_not_an_excel_formula_and_dates_are_dates(tmp_path):
    wb, _, _ = workbook_for(tmp_path, [atlas_row(**{"Libellé projet": '=HYPERLINK("https://example.com")',
                                              "Date comptable": pd.Timestamp("2026-01-01")})])
    sheet = wb["Résultats"]
    assert sheet["C2"].data_type == "s" and sheet["C2"].value.startswith("=")
    assert sheet["P2"].is_date and sheet["P2"].number_format == "dd/mm/yyyy"
    wb.close()


def test_empty_population_and_empty_atlas(tmp_path):
    for atlas in ([], [atlas_row(**{"Statut BAP": "Brouillon"})]):
        wb, _, _ = workbook_for(tmp_path, atlas, [])
        assert len(records(wb["Résultats"])) == len(atlas)
        assert records(wb["Tentatives"]) == []
        wb.close()


def test_split_sheets_without_lost_rows(tmp_path, monkeypatch):
    monkeypatch.setattr("reconciliation.exporters.excel.MAX_DATA_ROWS", 2)
    wb, _, _ = workbook_for(tmp_path, [atlas_row(Id=str(i)) for i in range(5)])
    rows = [r for name in wb.sheetnames if name.startswith("Résultats") for r in records(wb[name])]
    assert [r["Id"] for r in rows] == list(map(str, range(5)))
    assert "Résultats_3" in wb.sheetnames and "Tentatives_2" in wb.sheetnames
    wb.close()


def test_source_protection_and_trace_required(tmp_path):
    a, s = frames()
    path = tmp_path / "source.xlsx"
    path.write_bytes(b"source originale")
    result = match_reconciliations(a, s, collect_trace=True)
    with pytest.raises(ExportError, match="source"):
        export_reconciliation(a, result, path, source_paths={"Atlas": path})
    assert path.read_bytes() == b"source originale"
    with pytest.raises(ExportError, match="collect_trace"):
        export_reconciliation(a, match_reconciliations(a, s), tmp_path / "x.xlsx")


def test_conflicting_aliases_are_not_silently_lost():
    with pytest.raises(ExportError, match="contradictoires"):
        canonical_atlas(pd.DataFrame({"Libellé ligne budgetaire": ["A"], "Libellé ligne budgétaire": ["B"]}))


def test_cli_output(tmp_path, capsys):
    from reconciliation.main import main
    a, s, out = tmp_path / "atlas.xlsx", tmp_path / "sage.csv", tmp_path / "output" / "report.xlsx"
    pd.DataFrame([atlas_row()]).to_excel(a, index=False)
    pd.DataFrame([sage_row()]).to_csv(s, sep=";", index=False)
    assert main(["--atlas", str(a), "--sage", str(s), "--output", str(out)]) == 0
    wb = load_workbook(out)
    assert records(wb["Résultats"])[0]["Règle retenue"] == "MATCH_EXACT"
    assert "Classeur de rapprochement" in capsys.readouterr().out
    wb.close()
    assert out.with_suffix(".tentatives.jsonl").exists()


def test_failed_replace_keeps_existing_output_and_cleans_temporary(tmp_path, monkeypatch):
    a, s = frames()
    result = match_reconciliations(a, s, collect_trace=True)
    target = tmp_path / "previous.xlsx"
    target.write_bytes(b"previous workbook")

    def denied(*args):
        raise PermissionError("Classeur ouvert")

    monkeypatch.setattr("reconciliation.exporters.excel.os.replace", denied)
    with pytest.raises(ExportError, match="Classeur ouvert"):
        export_reconciliation(a, result, target)
    assert target.read_bytes() == b"previous workbook"
    assert list(tmp_path.iterdir()) == [target]
