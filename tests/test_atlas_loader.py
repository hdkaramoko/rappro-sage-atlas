"""Tests Atlas sur classeurs synthétiques."""

import pandas as pd
import pytest

from reconciliation.loaders.atlas import AtlasLoaderError, load_atlas


def workbook(tmp_path, sheets):
    path = tmp_path / "atlas.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, data in sheets.items():
            pd.DataFrame(data).to_excel(writer, sheet_name=name, index=False)
    return path


def test_multiple_sheets_empty_parasite_duplicates(tmp_path, caplog):
    path = workbook(tmp_path, {
        "Début": {"Id": ["001", "002"], "Code projet": ["P", "P"], "Extra": ["premier", "x"]},
        "Suite": {"Id": ["001", "003"], "Code projet": ["P", "P"], "Extra": ["second", "y"]},
        "Fin": {"Id": ["004"], "Code projet": ["P"]}, "Vide": {}, "Notes": {"Note": ["texte"]},
    })
    result = load_atlas(path)
    assert result.Id.tolist() == ["001", "002", "003", "004"]
    assert result.Extra.iloc[0] == "premier"
    assert result.attrs["load_summary"] == {
        "rows_read": 5, "duplicates_removed": 1, "rows_final": 4, "valid_sheets": 3,
    }
    assert "1 doublons" in caplog.text


def test_types_and_missing_values(tmp_path):
    path = workbook(tmp_path, {"JDD": {
        "Id": ["0001", "NA"], "Code projet": ["00123", "NULL"],
        "Date comptable": ["31/01/2026", None],
        "Total charges projet (€)": ["1 234,56", None], "Année": [2026, None],
    }})
    result = load_atlas(path)
    assert str(result.Id.dtype) == "string"
    assert result["Code projet"].tolist() == ["00123", "NULL"]
    assert result.Id.tolist() == ["0001", "NA"]
    assert str(result["Date comptable"].dtype) == "datetime64[ns]"
    assert result["Date comptable"].iloc[0] == pd.Timestamp("2026-01-31")
    assert result["Total charges projet (€)"].iloc[0] == 1234.56
    assert str(result["Total charges projet (€)"].dtype) == "Float64"
    assert str(result["Année"].dtype) == "Int64"
    assert pd.isna(result["Année"].iloc[1])


@pytest.mark.parametrize("data, message", [
    ({"Autre": ["x"]}, "Id"),
    ({"Id": [None], "Code projet": ["x"]}, "identifiants vides"),
    ({"Id": ["1"]}, "Code projet"),
])
def test_invalid_data(tmp_path, data, message):
    with pytest.raises(AtlasLoaderError, match=message):
        load_atlas(workbook(tmp_path, {"JDD": data}))


def test_missing_file(tmp_path):
    with pytest.raises(AtlasLoaderError, match="inexistant"):
        load_atlas(tmp_path / "absent.xlsx")


def test_coerce_invalid_values(tmp_path, caplog):
    path = workbook(tmp_path, {"JDD": {
        "Id": ["001", "002"], "Code projet": ["P", "P"],
        "Date comptable": ["invalide", "31/01/2026"],
        "Année": ["2026.5", "2026"],
        "Total charges projet (€)": ["invalide", "12,50"],
    }})
    result = load_atlas(path)
    for column, dtype in [
        ("Date comptable", "datetime64[ns]"), ("Année", "Int64"),
        ("Total charges projet (€)", "Float64"),
    ]:
        assert str(result[column].dtype) == dtype
        assert pd.isna(result[column].iloc[0])
        assert result.attrs["typing_issues"][column] == 1
    assert result["Année"].iloc[1] == 2026
    assert result["Total charges projet (€)"].iloc[1] == 12.5
    assert len(result) == 2
    assert "non convertibles" in caplog.text


@pytest.mark.parametrize("name", ["wrong.csv", "corrupt.xlsx"])
def test_wrong_or_corrupt_file(tmp_path, name):
    path = tmp_path / name
    path.write_text("invalide", encoding="utf-8")
    with pytest.raises(AtlasLoaderError):
        load_atlas(path)
