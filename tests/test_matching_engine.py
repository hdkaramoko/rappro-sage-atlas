"""Cascade, non-destruction, populations et contrat de sortie."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from reconciliation.matching import MatchingConfig, match_reconciliations, summarize_matching
from matching_helpers import atlas_row, sage_row, frames


def test_confirmed_without_sage_search():
    atlas, _ = frames([atlas_row(**{"N° pièce SAGE": "D", "Date comptable": pd.Timestamp("2026-01-01"),
                                  "Total charges SAGE (€)": 0, "Statut BAP": "\u00a0Envoyé SAGE  "})])
    result = match_reconciliations(atlas, pd.DataFrame()).iloc[0]
    assert result.match_rule == "MATCH_CONFIRMED_ATLAS"
    assert result.confidence == 1 and result.target_status == "Comptabilisé"
    assert result.sage_amount == 0 and result.candidate_count == 0


def test_population_immutability_and_duplicate_indices():
    atlas, sage = frames([atlas_row(), atlas_row(Id="002", **{"Statut BAP": "Comptabilisé"})])
    atlas.index = [5, 5]
    before_a, before_s = atlas.copy(deep=True), sage.copy(deep=True)
    result = match_reconciliations(atlas, sage)
    assert_frame_equal(atlas, before_a)
    assert_frame_equal(sage, before_s)
    assert len(result) == 1 and result.iloc[0].atlas_source_positions == (0,)
    assert result.attrs["population_summary"]["atlas_rows_excluded"] == 1
    assert summarize_matching(result)["MATCH_EXACT"] == 1
    assert sum(summarize_matching(result).values()) == 1


@pytest.mark.parametrize("atlas,sage", [([], []), ([atlas_row(**{"Statut BAP": None})], [])])
def test_empty_population(atlas, sage):
    result = match_reconciliations(*frames(atlas, sage))
    assert result.empty and "target_status" in result
    assert sum(summarize_matching(result).values()) == 0


def test_empty_sage():
    result = match_reconciliations(*frames(sage=[])).iloc[0]
    assert result.match_status == "UNMATCHED" and result.requires_review


@pytest.mark.parametrize("column", ["Code projet", "Code tiers SAGE", "N° BAP (SAGE)"])
def test_missing_key_never_matches_missing_key(column):
    mapping = {"Code projet": "Projet", "Code tiers SAGE": "Code Tiers - Tiers doc Orig", "N° BAP (SAGE)": "Référence"}
    result = match_reconciliations(*frames([atlas_row(**{column: None})], [sage_row(**{mapping[column]: None})])).iloc[0]
    assert result.match_status == "UNMATCHED"
    assert result.reason == "INCOMPLETE_STRUCTURED_KEY"


@pytest.mark.parametrize("options", [
    {"amount_tolerance": -1}, {"amount_tolerance": float("nan")},
    {"fuzzy_review_threshold": 0.99, "fuzzy_high_threshold": 0.9},
    {"fuzzy_high_threshold": 2}, {"amount_confidence": -0.1},
    {"fuzzy_method": "unknown"}, {"auto_account_rules": frozenset({"UNMATCHED"})},
])
def test_invalid_options(options):
    with pytest.raises(ValueError):
        MatchingConfig(**options)


def test_experimental_auto_account_is_explicit():
    data = frames([atlas_row(**{"Total charges projet (€)": 500}), atlas_row(Id="002", **{"Total charges projet (€)": 500})])
    default = match_reconciliations(*data).iloc[0]
    enabled = match_reconciliations(*data, MatchingConfig(auto_account_rules=frozenset({"MATCH_AMOUNT"}))).iloc[0]
    assert default.target_status is None and default.requires_review
    assert enabled.target_status == "Comptabilisé" and enabled.requires_review


def test_cli_matching(tmp_path, capsys):
    from reconciliation.main import main
    a, s = tmp_path / "a.xlsx", tmp_path / "s.csv"
    pd.DataFrame([atlas_row()]).to_excel(a, index=False)
    pd.DataFrame([sage_row()]).to_csv(s, sep=";", index=False)
    assert main(["--atlas", str(a), "--sage", str(s)]) == 0
    assert "MATCH_EXACT : 1" in capsys.readouterr().out
