"""Vérification de l'orchestration et des erreurs pour UiPath."""

import pandas as pd

from reconciliation.main import main


def test_cli_success(tmp_path, capsys):
    atlas = tmp_path / "atlas.xlsx"
    sage = tmp_path / "sage.csv"
    pd.DataFrame({"Id": ["001"], "Code projet": [" P "]}).to_excel(atlas, index=False)
    sage.write_text("Projet;Numéro pièce;Date comptable\n001;002;\n", encoding="utf-8")
    assert main(["--atlas", str(atlas), "--sage", str(sage)]) == 0
    output = capsys.readouterr().out
    assert "Atlas :" in output and "Sage :" in output
    assert "1 feuilles valides" in output
    assert output.count("1 lignes transformées") == 2
    assert output.count("0 codes projet manquants") == 2


def test_cli_failure(tmp_path, caplog):
    assert main([
        "--atlas", str(tmp_path / "absent.xlsx"),
        "--sage", str(tmp_path / "absent.csv"),
    ]) == 1
    assert "Chargement interrompu" in caplog.text
