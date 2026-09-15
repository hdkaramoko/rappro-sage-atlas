"""Aucun choix arbitraire de candidat, de pièce ou de date."""

import pandas as pd
import pytest

from reconciliation.matching import match_reconciliations
from matching_helpers import atlas_row, sage_row, frames


@pytest.mark.parametrize("labels", [["XYZ", "ABC"], ["JANVIER DUPONT FACTURE CONSULTANT", "FACTURE CONSULTANT DUPONT FEVRIER"]])
def test_multiple_candidates(labels):
    result = match_reconciliations(*frames(sage=[sage_row(**{"Libellé pièce": label}) for label in labels]))
    row = result.iloc[0]
    assert row.match_status == "AMBIGUOUS" and row.candidate_count == 2
    assert len(row.candidate_ids) == 2 and row.target_status is None
    assert len(result.attrs["sage_candidates"]) == 2


@pytest.mark.parametrize("change", [{"Numéro pièce": "DOC-02"}, {"Date comptable": pd.Timestamp("2026-02-01")}])
def test_incompatible_sage_evidence(change):
    s = [sage_row(**{"Charges (Dépenses)": 500}), sage_row(**{"Charges (Dépenses)": 500, **change})]
    row = match_reconciliations(*frames(sage=s)).iloc[0]
    assert row.match_status == "AMBIGUOUS" and row.target_status is None
    assert row.reason == "INCOMPATIBLE_SAGE_EVIDENCE"
    assert row.sage_document_number is None and pd.isna(row.sage_accounting_date)
    assert max(len(row.sage_document_numbers), len(row.sage_accounting_dates)) == 2


def test_shared_sage_candidate_independent_of_atlas_order():
    a = [atlas_row(), atlas_row(Id="002", **{"Libellé ATLAS": "JANVIER DUPONT FACTURE CONSULTANT"})]
    for rows in (a, list(reversed(a))):
        result = match_reconciliations(*frames(rows))
        assert result.match_status.tolist() == ["AMBIGUOUS", "AMBIGUOUS"]
        assert result.target_status.isna().all()
        assert set(result.reason) == {"SAGE_CANDIDATE_SHARED"}
