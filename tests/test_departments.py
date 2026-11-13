"""Recette des référentiels, du contrat et des inventaires organisationnels."""

import json
from time import perf_counter
from unittest.mock import patch

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

from reconciliation.departments import project_context, project_exports
from reconciliation.loaders.common import LoaderError
from reconciliation.main import main
from reconciliation_contract.departments import POLICY, validate_departments
from examples.ods_bap_filters_fixture import generate


def workbook(path, sheet, rows):
    """Écrit un petit Excel de test, sans toucher les données utilisateur."""
    book = Workbook()
    book.active.title = sheet
    for row in rows:
        book.active.append(row)
    book.save(path)
    book.close()
    return path


@pytest.fixture
def pole_configuration(monkeypatch):
    """Définit une liste suivie fictive uniquement dans le processus des tests."""
    monkeypatch.setattr("reconciliation.config.POLES_SUIVIS", ["Agriculture"])


@pytest.fixture(autouse=True)
def configured_poles(pole_configuration):
    """Conserve les tests du référentiel départemental avec une configuration explicite."""


@pytest.fixture
def inputs(tmp_path):
    """Prépare deux référentiels fictifs et des populations partiellement communes."""
    projects = workbook(tmp_path / "projects.xlsx", "Sheet1", [
        [" Code PROJET ", "Departement leader", "Département associé", "Montant total (€)", "Pôle"],
        [" p1 ", "Santé", "Autre", 50], ["P1", "Santé", None, 50],
        ["001", "Développement durable", None, 40], [None, None, None, None],
        ["TOTAL", None, None, 140], [None, None, None, "140.00"]])
    mapping = workbook(tmp_path / "mapping.xlsx", "Feuil1", [
        ["Département leader", "Département consolidé"], ["Santé", "SANTE"],
        ["Développement durable", "DEV_DURABLE"],
        *[(f"Département {i}", f"D{i}") for i in range(13)]])
    atlas = pd.DataFrame({"project_code": ["P1", "P1", "001", "ABSENT"]})
    sage = pd.DataFrame({"project_code": ["P1", "SAGE-ONLY", "SAGE-ONLY"]})
    return atlas, sage, projects, mapping


def test_reference_and_set_exports(inputs, tmp_path):
    """Les totaux sont reconnus ; les vrais projets et les absences restent exhaustifs."""
    atlas, sage, projects, mapping = inputs
    table, summary = project_context(*inputs)
    assert table["001"]["consolidated"] == "DEV_DURABLE"
    assert table["P1"]["source"] == "Santé"
    assert table["ABSENT"] == {"source": "", "consolidated": "", "in_reference": False, "pole": "Hors DP", "pole_source": ""}
    assert {key: summary[key] for key in ("atlas_projects", "sage_projects", "intersection", "sage_absent",
                                        "atlas_without_department", "reference_duplicates", "reference_totals")} == {"atlas_projects": 3, "sage_projects": 2, "intersection": 1, "sage_absent": 1,
                       "atlas_without_department": ["ABSENT"], "reference_duplicates": 1, "reference_totals": 2}
    before = atlas.copy(deep=True)
    paths = project_exports(atlas, sage, table, tmp_path, "test")
    sheets = []
    for path in paths:
        book = load_workbook(path, read_only=True)
        sheets.append(list(book.active.values))
        book.close()
    assert [r[0] for r in sheets[0][1:]] == ["001", "ABSENT", "P1"]
    assert sheets[1][1:] == [("SAGE-ONLY", 2)]
    pd.testing.assert_frame_equal(atlas, before)


@pytest.mark.parametrize("kind", ["header", "associated", "conflict", "unknown", "empty_code", "empty_department", "numeric_code", "invalid_code", "mapping_conflict", "mapping_empty"])
def test_invalid_references_fail_explicitly(inputs, kind):
    """Aucune donnée ambiguë ou invalide ne produit de département inventé."""
    _, _, projects, mapping = inputs
    if kind.startswith("mapping"):
        rows = [["Département leader", "Département consolidé"], ["Santé", "SANTE"],
                ["Santé", "AUTRE" if kind == "mapping_conflict" else None]]
        workbook(mapping, "Feuil1", rows)
    else:
        headers = ["Code projet", "Département leader", "Pôle"]
        row = ["P1", "Santé", None]
        extra = []
        if kind == "header":
            headers[0] = "Autre"
        if kind == "associated":
            headers[1] = "Département associé"
        if kind == "conflict":
            extra = [["P1", "Développement durable"]]
        if kind == "unknown":
            row[1] = "Inconnu"
        if kind == "empty_code":
            row[0] = None
        if kind == "empty_department":
            row[1] = None
        if kind == "numeric_code":
            row[0] = 1
        if kind == "invalid_code":
            row[0] = "??"
        workbook(projects, "Sheet1", [headers, row, *extra])
    with pytest.raises(LoaderError):
        project_context(*inputs)


def test_unicode_mapping_and_real_last_project(inputs):
    """Unicode décomposé et espaces correspondent, sans supprimer le dernier vrai projet."""
    atlas, sage, projects, mapping = inputs
    workbook(projects, "Sheet1", [["Code projet", "Département leader", "Pôle"], ["P1", "Sante\u0301", None], ["001", " Santé ", None]])
    table, summary = project_context(atlas, sage, projects, mapping)
    assert table["001"]["consolidated"] == "SANTE"
    assert table["P1"]["source"] == "Sante\u0301"
    assert summary["reference_totals"] == 0


def test_contract_rejects_contradictions():
    """Ancien en-tête accepté ; politique, booléens et couples source/cible contrôlés."""
    assert validate_departments({"schema_version": 3}) == {}
    for row in [{"source": "Santé", "consolidated": "", "in_reference": True},
                {"source": "", "consolidated": "AUTRES", "in_reference": False},
                {"source": "Santé", "consolidated": "SANTE", "in_reference": 1}]:
        with pytest.raises(ValueError):
            validate_departments({"schema_version": 3, "department_policy": POLICY, "project_departments": {"P": row}})


def test_export_does_not_change_matching_or_authorizations(tmp_path):
    """L'enrichissement modifie seulement l'en-tête et sa signature, pas les preuves/décisions."""
    before = [json.loads(s) for s in generate(tmp_path).read_text(encoding="utf-8").splitlines()]
    start = perf_counter()
    path = generate(tmp_path, project_departments={"P": {"source": "Santé", "consolidated": "SANTE", "in_reference": True}})
    after = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
    assert before[1:-1] == after[1:-1]
    assert after[0]["project_departments"]["P"]["consolidated"] == "SANTE"
    print(f"BENCH export enrichi synthétique : {perf_counter() - start:.3f}s")


def test_cli_arguments_remain_optional_but_paired():
    """Les anciennes options restent valides, un enrichissement incomplet est refusé."""
    with pytest.raises(SystemExit):
        main(["--atlas", "a.xlsx", "--sage", "s.csv", "--atlas-projects", "p.xlsx"])


def test_cli_unknown_department_publishes_nothing(inputs, tmp_path):
    """Une référence invalide échoue avant matching et conserve le JSONL existant."""
    atlas, sage, projects, mapping = inputs
    workbook(projects, "Sheet1", [["Code projet", "Département leader", "Pôle"], ["P1", "INCONNU", None]])
    output = tmp_path / "campaign.jsonl"
    output.write_text("previous", encoding="utf-8")
    summary = {"load_summary": {"valid_sheets": None, "rows_read": 4, "duplicates_removed": 0, "rows_final": 4},
               "transformation_summary": {"rows_transformed": 4, "missing_project_codes": 0}}
    atlas.attrs.update(summary)
    sage.attrs.update(summary)
    with patch("reconciliation.main.load_atlas", return_value=atlas), patch("reconciliation.main.load_sage", return_value=sage), \
         patch("reconciliation.main.transform_atlas", side_effect=lambda f: f), patch("reconciliation.main.transform_sage", side_effect=lambda f: f), \
         patch("reconciliation.main.match_reconciliations") as matching:
        assert main(["--atlas", "a.xlsx", "--sage", "s.csv", "--atlas-projects", str(projects),
                     "--department-mapping", str(mapping), "--review-output", str(output)]) == 1
        matching.assert_not_called()
    assert output.read_text(encoding="utf-8") == "previous"
    assert not list(tmp_path.glob("projets_*.xlsx"))


def test_cli_enriched_publishes_three_outputs(inputs, tmp_path):
    """Un vrai lancement publie le JSONL et les deux inventaires, sans second matching."""
    _, _, projects, mapping = inputs
    atlas = workbook(tmp_path / "atlas.xlsx", "JDD", [["Id", "Code projet", "Année", "Statut BAP",
        "Total charges projet (€)", "Total charges SAGE (€)", "N° pièce SAGE", "Date comptable"],
        ["A1", "P1", 2026, "Comptabilisé", 100, 100, "FAC1", "2026-01-01"]])
    sage = tmp_path / "sage.csv"
    sage.write_text("Projet;Numéro pièce;Date comptable;Charges (Dépenses);Journal;N° de ligne comptable;N° de ligne Analytique\nP1;FAC1;2026-01-01;100;ACH;1;1\nSAGE-ONLY;FAC2;2026-01-01;20;ACH;1;1\n", encoding="utf-8")
    output = tmp_path / "campaign.jsonl"
    assert main(["--atlas", str(atlas), "--sage", str(sage), "--atlas-projects", str(projects),
                 "--department-mapping", str(mapping), "--review-output", str(output), "--year", "2026"]) == 0
    header = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert header["project_departments"]["P1"]["consolidated"] == "SANTE"
    assert len(list(tmp_path.glob("projets_*.xlsx"))) == 2
    assert not list(tmp_path.glob(".departments-*"))


@pytest.mark.parametrize("source,expected", [("Agriculture", "Agriculture"), (" Agriculture  ", "Agriculture"),
    ("Autre pôle", "Hors DP"), (None, "Hors DP"), ("  ", "Hors DP")])
def test_pole_classification_and_source_audit(inputs, source, expected):
    """Un suivi conserve son nom exact ; les autres cas restent Hors DP avec source brute."""
    atlas, sage, projects, mapping = inputs
    workbook(projects, "Sheet1", [["Code projet", "Département leader", "Pôle"], ["P1", "Santé", source]])
    table, summary = project_context(atlas, sage, projects, mapping)
    assert table["P1"]["pole"] == expected
    assert table["P1"]["pole_source"] == (source or "")
    assert table["ABSENT"]["pole"] == "Hors DP"
    assert table["ABSENT"]["in_reference"] is False
    assert sum(summary["projects_by_pole"].values()) == 3


def test_pole_required_and_duplicate_conflict(inputs):
    """Pôle associé ne remplace pas Pôle ; deux rattachements différents sont refusés."""
    atlas, sage, projects, mapping = inputs
    workbook(projects, "Sheet1", [["Code projet", "Département leader", "Pôle associé"], ["P1", "Santé", "Agriculture"]])
    with pytest.raises(LoaderError, match="Pôle"):
        project_context(*inputs)
    workbook(projects, "Sheet1", [["Code projet", "Département leader", "Pôle"],
        ["P1", "Santé", "Agriculture"], ["P1", "Santé", "Autre"]])
    with pytest.raises(LoaderError, match="Pôles contradictoires"):
        project_context(*inputs)
    workbook(projects, "Sheet1", [["Code projet", "Département leader", "Pôle"],
        ["P1", "Santé", "Agriculture"], ["P1", "Santé", " Agriculture "]])
    assert project_context(*inputs)[1]["reference_duplicates"] == 1


def test_unconfigured_poles_fail_instead_of_inventing(inputs, monkeypatch):
    """None demande de configurer ; une liste vide explicitement choisie classe tout Hors DP."""
    monkeypatch.setattr("reconciliation.config.POLES_SUIVIS", None)
    with pytest.raises(LoaderError, match="POLES_SUIVIS"):
        project_context(*inputs)
    monkeypatch.setattr("reconciliation.config.POLES_SUIVIS", [])
    table, summary = project_context(*inputs)
    assert all(row["pole"] == "Hors DP" for row in table.values())


def test_pole_contract_and_business_non_regression(tmp_path):
    """La nouvelle politique signe les métadonnées sans changer aucun enregistrement métier."""
    from reconciliation_contract.departments import POLE_POLICY
    original = {"P": {"source": "Santé", "consolidated": "SANTE", "in_reference": True}}
    before = [json.loads(s) for s in generate(tmp_path, project_departments=original).read_text(encoding="utf-8").splitlines()]
    enriched = {"P": {**original["P"], "pole": "Agriculture", "pole_source": " Agriculture "}}
    path = generate(tmp_path, project_departments=enriched,
                    pole_configuration={"followed": ["Agriculture"], "fallback": "Hors DP"})
    after = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
    assert after[0]["pole_policy"] == POLE_POLICY
    assert before[1:-1] == after[1:-1]
    validate_departments(after[0])
    after[0]["project_departments"]["P"]["pole"] = "Inventé"
    with pytest.raises(ValueError, match="contradictoire"):
        validate_departments(after[0])
