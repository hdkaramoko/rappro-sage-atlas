"""Tests Sage indépendants des fichiers métier."""

import pandas as pd
import pytest

from reconciliation.loaders.sage import SageLoaderError, load_sage


@pytest.mark.parametrize("separator, encoding", [
    (";", "utf-8-sig"), (",", "utf-8"), (";", "cp1252"),
])
def test_read_types_duplicates(tmp_path, separator, encoding):
    path = tmp_path / "sage.csv"
    row = {
        "Projet": "001", "Numéro pièce": "00012", "Journal": "NA",
        "Date comptable": "31/01/2026", "Charges (Dépenses)": "1\u00a0234,56",
        "Extra": "préservé",
    }
    pd.DataFrame([row, row]).to_csv(path, sep=separator, encoding=encoding, index=False)
    result = load_sage(path)
    assert len(result) == 1
    assert result.Projet.iloc[0] == "001"
    assert result["Numéro pièce"].iloc[0] == "00012"
    assert result.Journal.iloc[0] == "NA"
    assert str(result.Projet.dtype) == "string"
    assert str(result["Date comptable"].dtype) == "datetime64[ns]"
    assert result["Date comptable"].iloc[0] == pd.Timestamp("2026-01-31")
    assert result["Charges (Dépenses)"].iloc[0] == 1234.56
    assert result.Extra.iloc[0] == "préservé"
    assert result.attrs["load_summary"]["duplicates_removed"] == 1


def test_only_strict_source_duplicates_and_missing(tmp_path):
    path = tmp_path / "sage.csv"
    path.write_text(
        "Projet;Numéro pièce;Charges (Dépenses);Date comptable\n"
        "001;01;1,0;\n001;01;1,00;\n002;02;;\n", encoding="utf-8",
    )
    result = load_sage(path)
    assert len(result) == 3
    assert pd.isna(result["Charges (Dépenses)"].iloc[2])
    assert result["Date comptable"].isna().all()


@pytest.mark.parametrize("content, message", [
    ("Projet;Autre\n1;x\n", "Numéro pièce"),
    ("", "vide"),
    ("Projet;Numéro pièce\n1;2\n", "Date comptable"),
    ('Projet;Numéro pièce;Date comptable\n1;"non terminé', "charger Sage"),
    ("Projet;Numéro pièce;Projet;Date comptable\n1;2;3;\n", "dupliquées"),
])
def test_invalid_csv(tmp_path, content, message):
    path = tmp_path / "sage.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SageLoaderError, match=message):
        load_sage(path)


def test_explicit_settings(tmp_path):
    path = tmp_path / "sage.csv"
    path.write_text("Projet;Numéro pièce;Taux de TVA;Date comptable\n001;002;20.5;", encoding="utf-8")
    assert load_sage(path, separator=";", decimal=".")["Taux de TVA"].iloc[0] == 20.5


def test_missing_file(tmp_path):
    with pytest.raises(SageLoaderError, match="inexistant"):
        load_sage(tmp_path / "absent.csv")


def test_coerce_invalid_values(tmp_path, caplog):
    path = tmp_path / "sage.csv"
    path.write_text(
        "Projet;Numéro pièce;Date comptable;Charges (Dépenses)\n"
        "001;002;invalide;abc\n001;003;31/01/2026;12,5\n",
        encoding="utf-8",
    )
    result = load_sage(path)
    assert len(result) == 2
    assert str(result["Date comptable"].dtype) == "datetime64[ns]"
    assert str(result["Charges (Dépenses)"].dtype) == "Float64"
    assert pd.isna(result["Date comptable"].iloc[0])
    assert pd.isna(result["Charges (Dépenses)"].iloc[0])
    assert result["Charges (Dépenses)"].iloc[1] == 12.5
    assert result.attrs["typing_issues"] == {"Date comptable": 1, "Charges (Dépenses)": 1}
    assert "non convertibles" in caplog.text


def test_wrong_extension(tmp_path):
    path = tmp_path / "sage.xlsx"
    path.touch()
    with pytest.raises(SageLoaderError, match="Type de fichier"):
        load_sage(path)
