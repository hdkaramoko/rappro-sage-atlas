"""Scores RapidFuzz, seuils et restriction des candidats."""

import pytest

from reconciliation.matching import match_reconciliations, MatchingConfig
from reconciliation.matching.fuzzy import compute_label_similarity
from matching_helpers import atlas_row, sage_row, frames


def test_token_set_handles_word_order():
    a, b = "FACTURE CONSULTANT DUPONT JANVIER", "JANVIER DUPONT FACTURE CONSULTANT"
    assert compute_label_similarity(a, b) == 1
    assert compute_label_similarity(a, b, "ratio") < 0.85
    assert compute_label_similarity(None, b) == 0
    row = match_reconciliations(*frames(sage=[sage_row(**{"Libellé pièce": b})])).iloc[0]
    assert row.match_rule == "MATCH_FUZZY_HIGH" and row.requires_review
    assert row.label_similarity == 1 and row.target_status is None


def test_medium_similarity():
    a, b = "FACTURE CONSULTANT DUPONT JANVIER", "FACTURE CONSULTANT DUPONT FEVRIER"
    assert 0.85 <= compute_label_similarity(a, b) < 0.95
    row = match_reconciliations(*frames(sage=[sage_row(**{"Libellé pièce": b})])).iloc[0]
    assert row.match_rule == "MATCH_FUZZY_REVIEW" and row.requires_review


@pytest.mark.parametrize("change", [{"Projet": "OTHER"}, {"Référence": "OTHER"},
                                   {"Code Tiers - Tiers doc Orig": "OTHER"}, {"Charges (Dépenses)": 2000}])
def test_fuzzy_never_scores_outside_block(monkeypatch, change):
    def forbidden(*args, **kwargs):
        raise AssertionError("Candidat hors bloc transmis au fuzzy")
    monkeypatch.setattr("reconciliation.matching.fuzzy.compute_label_similarity", forbidden)
    row = match_reconciliations(*frames(sage=[sage_row(**change)])).iloc[0]
    assert row.match_status == "UNMATCHED"


def test_without_label_and_disabled_fallback():
    data = frames(sage=[sage_row(**{"Libellé pièce": "XYZ"})])
    row = match_reconciliations(*data).iloc[0]
    assert row.match_rule == "MATCH_WITHOUT_LABEL" and row.requires_review
    assert match_reconciliations(*data, MatchingConfig(enable_without_label=False)).iloc[0].match_status == "UNMATCHED"


def test_missing_labels_only_use_fallback():
    row = match_reconciliations(*frames([atlas_row(**{"Libellé ATLAS": None})], [sage_row(**{"Libellé pièce": None})])).iloc[0]
    assert row.match_rule == "MATCH_WITHOUT_LABEL"
