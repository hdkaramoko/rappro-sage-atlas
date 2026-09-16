"""Préfiltrage sans changement des décisions, des positions ou du journal global."""

import pandas as pd
import pytest

from matching_helpers import atlas_row, sage_row, frames
from reconciliation.matching import MatchingConfig, match_reconciliations


@pytest.mark.parametrize("label,amount", [("FACTURE CONSULTANT DUPONT JANVIER", 1000), ("XYZ", 1000), (None, 1000), ("XYZ", None)])
def test_prefilter_preserves_full_results_and_attempts(label, amount):
    a, s = frames(sage=[sage_row(Projet="EXCLU"), sage_row(**{"Libellé pièce": label, "Charges (Dépenses)": amount}),
                       sage_row(**{"Référence": None}), sage_row(Projet="EXCLU-2")])
    s.index = [7, 7, 7, 7]
    before = s.copy(deep=True)
    filtered = match_reconciliations(a, s, collect_trace=True)
    full = match_reconciliations(a, s, MatchingConfig(prefilter_sage=False), collect_trace=True)
    pd.testing.assert_frame_equal(filtered, full)
    assert filtered.attrs["matching_attempts"] == full.attrs["matching_attempts"]
    pd.testing.assert_frame_equal(s, before)
    assert filtered.attrs["population_summary"]["sage_rows_retained"] == 1
    assert filtered.attrs["population_summary"]["sage_groups_total"] == 4
    if filtered.iloc[0].match_status == "MATCHED":
        assert filtered.iloc[0].sage_source_ids == (1,)
        assert filtered.iloc[0].sage_group_id == "SAGE:1"


def test_all_rows_of_a_block_are_kept_even_with_missing_amounts():
    a, s = frames(sage=[sage_row(), sage_row(**{"Charges (Dépenses)": None}), sage_row(Projet="EXCLU")])
    result = match_reconciliations(a, s)
    assert result.attrs["population_summary"]["sage_rows_retained"] == 2
    assert result.iloc[0].match_status == "UNMATCHED"  # Ne jamais produire une somme partielle.


def test_no_eligible_block_preserves_unmatched_and_global_counts():
    a, s = frames([atlas_row(**{"N° BAP (SAGE)": None})])
    result = match_reconciliations(a, s)
    assert result.attrs["population_summary"]["sage_rows_retained"] == 0
    assert result.attrs["population_summary"]["sage_groups_total"] == 1
    assert result.iloc[0].reason == "INCOMPLETE_STRUCTURED_KEY"


def test_proof_only_skips_sage_preparation():
    a, _ = frames([atlas_row(**{"N° pièce SAGE": "D", "Date comptable": pd.Timestamp("2026-01-01"), "Total charges SAGE (€)": 1000})])
    result = match_reconciliations(a, pd.DataFrame())
    assert not result.attrs["population_summary"]["sage_prefilter_applied"]
    assert result.iloc[0].match_rule == "MATCH_CONFIRMED_ATLAS"
