"""Clé complète, priorité de la preuve et qualité des enrichissements."""

import pandas as pd
import pytest

from reconciliation.matching import match_reconciliations
from matching_helpers import atlas_row, sage_row, frames


def test_strict_three_rows_and_provenance():
    atlas = [atlas_row(Id=str(i), **{"Total charges projet (€)": 500}) for i in range(3)]
    sage = [sage_row(**{"Charges (Dépenses)": 500}) for _ in range(3)]
    row = match_reconciliations(*frames(atlas, sage)).iloc[0]
    assert row.match_rule == "MATCH_EXACT" and row.confidence == 1
    assert row.atlas_row_count == row.sage_row_count == 3
    assert row.atlas_amount == row.sage_amount == 1500
    assert row.atlas_source_ids == ("0", "1", "2")
    assert row.sage_source_ids == (0, 1, 2)
    assert row.sage_document_number == "DOC-01"
    assert row.sage_accounting_date == pd.Timestamp("2026-01-31")
    assert row.target_status == "Comptabilisé" and not row.requires_review


@pytest.mark.parametrize("missing", ["Numéro pièce", "Date comptable"])
def test_incomplete_evidence_prevents_automatic_status(missing):
    row = match_reconciliations(*frames(sage=[sage_row(**{missing: None})])).iloc[0]
    assert row.match_rule == "MATCH_EXACT"
    assert row.requires_review and row.target_status is None
    assert row.reason == "INCOMPLETE_SAGE_EVIDENCE"


def test_partial_atlas_evidence_searches_sage():
    row = match_reconciliations(*frames([atlas_row(**{"N° pièce SAGE": "OLD"})])).iloc[0]
    assert row.match_rule == "MATCH_EXACT" and row.sage_document_number == "DOC-01"


def test_structured_normalization():
    row = match_reconciliations(*frames([atlas_row(**{"Code projet": " p ", "Code tiers SAGE": " t ", "N° BAP (SAGE)": " b "})])).iloc[0]
    assert row.match_rule == "MATCH_EXACT"
