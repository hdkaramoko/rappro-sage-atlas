"""Recette synthétique du lot 1 : signatures, décimales, exclusions et allocations."""

import copy
import json

import pandas as pd
import pytest

from reconciliation.exporters.review import export_review_bundle
from reconciliation.loaders.sage import load_sage
from reconciliation.multiples import build_controls, inventory_rows
from reconciliation.sage_inventory import inventory_records
from reconciliation_contract import control_identity, entry_from_sage
from reconciliation_contract.sage_inventory import consolidate, exclusion_policy, inventory_record, validate_inventory_record
from test_multiples import atlas_row, sage_row, match_reconciliations


def source(amount="6000", **changes):
    """Retourne une ligne Atlas canonique Comptabilisé pour les calculs purs."""
    return next(inventory_rows(pd.DataFrame([atlas_row(**{"Total charges SAGE (€)": amount, **changes})])))


def record(amount="10000", policy=None, **changes):
    """Retourne une écriture Sage signée, avec identifiants à zéros initiaux."""
    return inventory_record(entry_from_sage(sage_row(**{"Charges (Dépenses)": amount, **changes})), policy or exclusion_policy())


def calculate(atlas=None, records=None, allocations=None, **options):
    """Calcule un groupe standard ou ODS depuis de petites populations synthétiques."""
    atlas = [source()] if atlas is None else atlas
    records = [record()] if records is None else records
    identity = control_identity(atlas[0]) if atlas else control_identity(records[0]["entry"], sage=True)
    return consolidate(identity, atlas, records, allocations or [], **options)


@pytest.mark.parametrize("prefixes,expected", [([], []), ([" fac ", "oDs", "FAC"], ["FAC", "ODS"])])
def test_normalized_exclusion_policy(prefixes, expected):
    """Une politique vide n'exclut rien ; casse et bords sont normalisés."""
    assert exclusion_policy(prefixes)["prefixes"] == expected


@pytest.mark.parametrize("prefixes", ["FAC", None, [None], ["FA"], ["FA C"], ["ÉÉÉ"], ["ABCD"], [123]])
def test_invalid_policies(prefixes):
    """Les configurations mal formées sont refusées avant publication."""
    with pytest.raises(ValueError):
        exclusion_policy(prefixes)


def test_excluded_entries_and_missing_documents_are_preserved():
    """L'exclusion n'efface aucune écriture ; une pièce absente reste à examiner."""
    excluded = record(policy=exclusion_policy(["FAC"]), **{"Numéro pièce": "FAC001"})
    assert not excluded["eligible"]
    assert calculate(atlas=[], records=[excluded])["state"] == "EXCLU"
    missing = record(**{"Numéro pièce": ""})
    assert missing["eligible"]
    assert calculate(atlas=[], records=[missing])["state"] == "INDETERMINE"


@pytest.mark.parametrize("amount,expected", [("10000", "EQUILIBRE"), ("10000.01", "EQUILIBRE"), ("10000.02", "ECART"), (None, "INDETERMINE")])
def test_standard_tolerance_and_missing_amounts(amount, expected):
    """La frontière du centime est incluse ; une absence n'est jamais un zéro."""
    assert calculate(atlas=[source(amount)])["state"] == expected


def test_individual_sums_and_negative_amounts():
    """Les sommes individuelles préservent les signes et n'utilisent aucun sage_total."""
    first, second = source("6000"), source("4000")
    second["source_id"] = "B"
    result = calculate(atlas=[first, second], records=[record("6000"), record("4000", **{"N° de ligne comptable": "002"})])
    assert result["state"] == "EQUILIBRE"
    assert calculate(atlas=[source("-100")], records=[record("-100")])["state"] == "EQUILIBRE"
    assert calculate(atlas=[source("0")], records=[record("0")])["state"] == "EQUILIBRE"


def test_confirmed_allocation_balances_without_losing_initial_gap():
    """6000 comptabilisés + 4000 confirmés expliquent la pièce Sage de 10000."""
    rows = [record("6000"), record("4000", **{"N° de ligne comptable": "002"})]
    allocation = {"line_key": "B", "amount": "4000", "refs": [rows[1]["entry"]["ref"]],
                  "validated": True, "current": True, "source_status": "Envoyé SAGE"}
    before = calculate(records=rows)
    assert before["gap"] == "-4000.00"
    after = calculate(records=rows, allocations=[allocation])
    assert after["accounted_state"] == "ECART"
    assert after["state"] == "EQUILIBRE"
    assert after["gap"] == "0.00"
    for field, value in [("validated", False), ("current", False), ("source_status", "Comptabilisé")]:
        assert calculate(records=rows, allocations=[{**allocation, field: value}])["state"] == "ECART"
    assert calculate(records=rows, allocations=[allocation, {**allocation, "line_key": "C"}])["state"] == "INDETERMINE"


def test_partial_allocation_requires_explicit_validated_trace():
    """Une seule référence peut porter une fraction explicite validée, jamais implicite."""
    row = record()
    allocation = {"line_key": "B", "amount": "4000", "refs": [row["entry"]["ref"]],
                  "validated": True, "current": True, "source_status": "Envoyé SAGE"}
    assert calculate(records=[row], allocations=[allocation])["state"] == "INDETERMINE"
    assert calculate(records=[row], allocations=[{**allocation, "partial_validated": True}])["state"] == "EQUILIBRE"


def test_collisions_multiple_journals_and_scope_mismatches():
    """Un solde nul ne blanchit pas les collisions ou les écritures hors clé."""
    assert calculate(atlas=[source("10000")], records=[record("6000"), record("4000")])["state"] == "INDETERMINE"
    assert calculate(atlas=[source("10000")], records=[record("6000"), record("4000", Journal="VEN")])["state"] == "INDETERMINE"
    assert calculate(atlas=[source("10000")], records=[record(Projet="OTHER")])["state"] == "INDETERMINE"
    assert calculate(atlas=[source("10000")], records=[record(**{"Date comptable": "2025-01-01"})])["state"] == "INDETERMINE"


@pytest.mark.parametrize("atlas_label,sage_label,expected", [("Café mission", "CAFE MISSION", "EQUILIBRE"), ("", "", "EQUILIBRE"), ("", "mission", "INDETERMINE"), ("alpha", "beta", "INDETERMINE")])
def test_ods_unique_group_with_or_without_label(atlas_label, sage_label, expected):
    """ODS ignore les numéros intersources ; seul un groupe unique fiable est automatique."""
    a = source("10000", **{"N° pièce SAGE": "ODS-ATLAS", "Libellé ATLAS": atlas_label})
    s = record(**{"Numéro pièce": "ODG-SAGE", "Libellé pièce": sage_label})
    result = calculate(atlas=[a], records=[s])
    assert result["state"] == expected
    assert result["auto_validated"] == (expected == "EQUILIBRE")
    second = record("0", **{"Numéro pièce": "ODG-SAGE2", "Libellé pièce": sage_label})
    assert calculate(atlas=[a], records=[s, second])["state"] == "INDETERMINE"


def test_ods_amount_mismatch_and_prefix_journal_disagreement():
    """Une égalité composite n'efface ni écart monétaire ni convention contradictoire."""
    a = source("10000", **{"N° pièce SAGE": "ODS-A", "Libellé ATLAS": ""})
    s = record("9000", **{"Numéro pièce": "ODS-S", "Libellé pièce": ""})
    assert calculate(atlas=[a], records=[s])["state"] == "ECART"
    s = record(**{"Numéro pièce": "FAC123", "Journal": "ODS", "Libellé pièce": ""})
    assert calculate(atlas=[a], records=[s])["state"] == "INDETERMINE"


def test_inventory_signatures_and_decimal_source(tmp_path):
    """Le loader déduplique strictement et préserve les décimales sans arrondi binaire."""
    path = tmp_path / "sage.csv"
    pd.DataFrame([sage_row(**{"Charges (Dépenses)": "123456789.123456"})] * 2).to_csv(path, sep=";", index=False)
    frame = load_sage(path, decimal=".")
    records = list(inventory_records(frame, exclusion_policy()))
    assert len(records) == 1
    assert records[0]["entry"]["amount"] == "123456789.123456"
    assert records[0]["entry"]["line"] == "001"
    validate_inventory_record(records[0], exclusion_policy())
    altered = copy.deepcopy(records[0])
    altered["entry"]["amount"] = "999"
    with pytest.raises(ValueError):
        validate_inventory_record(altered, exclusion_policy())


def test_distinct_sources_with_same_canonical_identity_are_preserved(tmp_path):
    """Deux sources distinctes après déduplication restent deux preuves en collision."""
    path = tmp_path / "distinct.csv"
    pd.DataFrame([sage_row(**{"Produits (Recettes)": "0"}),
                  sage_row(**{"Produits (Recettes)": "1"})]).to_csv(path, sep=";", index=False)
    records = list(inventory_records(load_sage(path), exclusion_policy()))
    assert len(records) == 2
    assert records[0]["record_id"] != records[1]["record_id"]
    assert records[0]["entry"]["ref"] == records[1]["entry"]["ref"]
    assert calculate(atlas=[source("200")], records=records)["state"] == "INDETERMINE"


def test_full_inventory_export_and_atomic_failure(tmp_path):
    """Sans proposition Atlas, toutes les écritures Sage sont exportées et signées."""
    atlas = pd.DataFrame([atlas_row()])
    sage = pd.DataFrame([sage_row(), sage_row(Projet="OTHER", **{"Numéro pièce": "XXX001"})])
    result = match_reconciliations(atlas, sage)
    path = export_review_bundle(atlas, sage, result, tmp_path / "lot1.jsonl", controls=build_controls(atlas, sage, result), include_sage_inventory=True, excluded_prefixes=["XXX"])
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["capabilities"] == ["sage_inventory_v1"]
    assert records[-1]["sage_inventory_count"] == 2
    assert len([r for r in records if r.get("type") == "proposal"]) == 0
    original = path.read_bytes()

    def broken_controls():
        """Simule une erreur tardive, après écriture de la photographie temporaire."""
        yield from ()
        raise ValueError("échec simulé")

    with pytest.raises(ValueError):
        export_review_bundle(atlas, sage, result, path, controls=broken_controls(), include_sage_inventory=True)
    assert path.read_bytes() == original
