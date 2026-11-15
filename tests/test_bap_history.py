"""Lecture et transport de l'historique informatif BAP, sans changement du matching."""

from datetime import datetime
import json
from unittest.mock import patch

import pandas as pd
import pytest
from openpyxl import Workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904

from reconciliation.bap_history import COLUMNS, excel_datetime, history_context
from reconciliation.loaders.common import LoaderError
from reconciliation_contract.bap_history import FIELDS, bap_key, validate_record
from examples.ods_bap_filters_fixture import generate


def workbook(path, rows, *, headers=(*COLUMNS, "Code projet", "Total dépenses (€)", "Id"), epoch=None):
    """Écrit un Excel fictif avec dates brutes, uniquement dans le dossier temporaire."""
    book = Workbook()
    book.active.title = "Sheet1"
    if epoch:
        book.epoch = epoch
    book.active.append(headers)
    for row in rows:
        book.active.append(row)
    book.save(path)
    book.close()
    return path


def atlas(*pairs):
    """Prépare le seul contexte de jointure ; montants et matching n'interviennent pas."""
    return pd.DataFrame(pairs, columns=["project_code", "N° BAP (SAGE)"])


def record(**changes):
    """Retourne un contexte BAP fictif conforme au contrat partagé."""
    return {"project_code": "P", "bap_sage_number": "BAP-TARGET", "bap_created_at": "2026-01-02T15:30:00",
            "bap_created_by": "Auteur test", "bap_modified_at": "2026-01-03T17:00:00", "bap_modified_by": "Modificateur test", **changes}


def test_serial_dates_authors_footers_and_single_open(tmp_path):
    """Deux lignes Atlas d'un BAP partagent le même contexte ; totaux détectés par contenu."""
    path = workbook(tmp_path / "bap.xlsx", [[" bap - target ", 46024.5, "Auteur test", 46025.75, "Auteur 2", "P"],
        ["Total"], [None] * 6 + ["1 234,56"], [None] * 8])
    from reconciliation.bap_history import load_workbook
    with patch("reconciliation.bap_history.load_workbook", wraps=load_workbook) as opening:
        rows, summary = history_context(path, atlas(("P", "BAP-TARGET"), ("P", "BAP-TARGET"), ("P", "BAP-MISSING")))
    opening.assert_called_once()
    assert len(rows) == 1
    assert rows[0]["bap_created_at"].endswith("T12:00:00")
    assert rows[0]["bap_modified_at"].endswith("T18:00:00")
    assert rows[0]["bap_created_by"] == "Auteur test"
    assert summary["total_rows"] == 2
    assert summary["jdd_baps_without_history"] == 1
    assert "Auteur test" not in json.dumps(summary)


@pytest.mark.parametrize("kind", ["missing_column", "wrong_sheet", "unreadable"])
def test_invalid_workbook(tmp_path, kind):
    """Les erreurs structurelles sont explicites, avant toute publication."""
    path = tmp_path / "bad.xlsx"
    if kind == "unreadable":
        path.write_text("not an Excel file")
    else:
        workbook(path, [], headers=COLUMNS[:-1] if kind == "missing_column" else COLUMNS)
        if kind == "wrong_sheet":
            from openpyxl import load_workbook
            book = load_workbook(path)
            book.active.title = "Other"
            book.save(path)
            book.close()
    with pytest.raises(LoaderError):
        history_context(path, atlas(("P", "BAP-TARGET")))


def test_invalid_cells_duplicates_and_project_mismatch(tmp_path):
    """Clés invalides et dates sont comptées ; ambiguïtés neutralisées par couple BAP/projet."""
    rows = [["BAP-A", "invalid", "A", None, None, "P"],
            ["BAP-A", "invalid", "A", None, None, "P"],
            ["BAP-B", None, "A", None, None, "P"], ["BAP-B", None, "B", None, None, "P"],
            [None, None, "A", None, None, "P"], ["NA", None, "A", None, None, "P"],
            ["BAP-C", None, "A", None, None, "Q"], ["BAP-UNUSED", None, None, None, None, "P"]]
    result, summary = history_context(workbook(tmp_path / "b.xlsx", rows), atlas(("P", "BAP-A"), ("P", "BAP-B"), ("P", "BAP-C")))
    assert [r["bap_sage_number"] for r in result] == ["BAP-A"]
    assert result[0]["bap_created_at"] is None
    assert summary["duplicates"] == 1 and summary["conflicts"] == 1
    assert summary["invalid_dates"] == 2 and summary["invalid_keys"] == 2
    assert summary["project_mismatches"] == 1 and summary["extract_baps_not_in_jdd"] == 1


def test_optional_project_and_collision_are_prudent(tmp_path):
    """Un projet absent autorise une jointure unique ; une source contradictoire sans projet bloque."""
    path = workbook(tmp_path / "b.xlsx", [["BAP-A", None, "A", None, None]], headers=COLUMNS)
    rows, _ = history_context(path, atlas(("P", "BAP-A"), ("Q", "BAP-A")))
    assert len(rows) == 2
    path = workbook(path, [["BAP-A", None, "A", None, None, "P"], ["BAP-A", None, "B", None, None, None]])
    rows, summary = history_context(path, atlas(("P", "BAP-A")))
    assert rows == [] and summary["ambiguous_targets"] == 1
    path = workbook(path, [["BAP-A", None, "A", None, None, "Q"], ["BAP-A", None, "B", None, None, None]])
    rows, summary = history_context(path, atlas(("P", "BAP-A")))
    assert rows == [] and summary["ambiguous_targets"] == 1


def test_dates_support_epoch_and_do_not_invent_timezone():
    """Sériels 1904, datetime naïve/aware, absence et valeurs invalides restent distincts."""
    assert excel_datetime(1.5, CALENDAR_MAC_1904)[0] == "1904-01-02T12:00:00"
    assert excel_datetime(datetime(2026, 1, 2, 15, 30), CALENDAR_MAC_1904)[0] == "2026-01-02T15:30:00"
    assert excel_datetime("2026-01-02T15:30:00+02:00", CALENDAR_MAC_1904)[0].endswith("+02:00")
    assert excel_datetime(None, CALENDAR_MAC_1904) == (None, False)
    for invalid in (True, "not a date", float("nan"), 0.5):
        assert excel_datetime(invalid, CALENDAR_MAC_1904) == (None, True)


def test_context_does_not_change_any_business_record(tmp_path):
    """Avec ou sans nouvelle option, toutes les preuves et autorisations restent identiques."""
    before = [json.loads(s) for s in generate(tmp_path).read_text(encoding="utf-8").splitlines()]
    after = [json.loads(s) for s in generate(tmp_path, bap_history=[record()]).read_text(encoding="utf-8").splitlines()]
    assert [r for r in after[1:-1] if r["type"] != "bap_history"] == before[1:-1]
    assert after[-1]["bap_history_count"] == 1
    assert not any("bap_created_at" in r.get("atlas", {}) for r in after)


def test_real_example_is_readable():
    """L'exemple fourni respecte les dates et les deux pieds sans divulguer les auteurs."""
    from pathlib import Path
    path = Path("data/inputs/ExtractionBapTest.xlsx")
    if not path.exists():
        pytest.skip("Exemple privé absent")
    rows, summary = history_context(path, atlas(("22REX0C166", "BAPPJT221002173")))
    assert len(rows) == 1
    assert rows[0]["bap_created_at"].startswith("2022-10-19T17:40:18")
    assert summary["total_rows"] == 2


def test_contract_rejects_invalid_context():
    """Les champs attendus et les dates ISO sont stricts ; les absences sont nulles."""
    assert bap_key(" BAP ETR 2601 ") == "BAPETR2601"
    for changes in ({"bap_created_at": "invalid"}, {"bap_created_at": 4}, {"project_code": ""}, {"bap_created_by": "x" * 256}):
        with pytest.raises(ValueError):
            validate_record(record(**changes))
    assert validate_record(record(**{key: None for key in FIELDS}))


def test_cli_optional_bap_extract(tmp_path):
    """La commande documentée transporte l'historique ; sans option les preuves sont identiques."""
    from reconciliation.main import main
    left = tmp_path / "atlas.xlsx"
    pd.DataFrame([{"Id": "A", "Code projet": "P", "Année": 2026, "Statut BAP": "Comptabilisé",
        "N° BAP (SAGE)": "BAPTEST", "Total charges projet (€)": 100, "Total charges SAGE (€)": 100,
        "N° pièce SAGE": "FAC1", "Date comptable": "2026-01-01"}]).to_excel(left, index=False)
    right = tmp_path / "sage.csv"
    right.write_text("Projet;Numéro pièce;Date comptable;Charges (Dépenses);Journal;N° de ligne comptable;N° de ligne Analytique\nP;FAC1;2026-01-01;100;ACH;1;1\n", encoding="utf-8")
    extraction = workbook(tmp_path / "history.xlsx", [["BAPTEST", 46024.5, "Auteur test", None, None, "P"]])
    before, after = tmp_path / "before.jsonl", tmp_path / "after.jsonl"
    args = ["--atlas", str(left), "--sage", str(right), "--year", "2026"]
    assert main([*args, "--review-output", str(before)]) == 0
    assert main([*args, "--review-output", str(after), "--bap-extract", str(extraction)]) == 0
    first = [json.loads(s) for s in before.read_text(encoding="utf-8").splitlines()]
    second = [json.loads(s) for s in after.read_text(encoding="utf-8").splitlines()]
    assert second[-1]["bap_history_count"] == 1
    assert [r for r in second[1:-1] if r["type"] != "bap_history"] == first[1:-1]
    assert "bap_history_policy" not in first[0]
