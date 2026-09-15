"""Sommes complètes, cardinalité et frontières de tolérance."""

import pytest

from reconciliation.matching import match_reconciliations
from reconciliation.matching.aggregated import amounts_compatible
from matching_helpers import atlas_row, sage_row, frames


def test_amount_different_cardinality():
    a = [atlas_row(Id=str(i), **{"Total charges projet (€)": 750}) for i in range(2)]
    s = [sage_row(**{"Charges (Dépenses)": 500}) for _ in range(3)]
    row = match_reconciliations(*frames(a, s)).iloc[0]
    assert row.match_rule == "MATCH_AMOUNT" and row.requires_review
    assert row.atlas_row_count == 2 and row.sage_row_count == 3
    assert row.target_status is None and not row.cardinality_match


@pytest.mark.parametrize("amount,expected", [(1000.005, True), (1000.01, True), (1000.011, False), (None, False)])
def test_tolerance(amount, expected):
    assert amounts_compatible(1000, amount, 0.01) is expected
    row = match_reconciliations(*frames(sage=[sage_row(**{"Charges (Dépenses)": amount})])).iloc[0]
    assert (row.match_rule == "MATCH_EXACT") is expected


@pytest.mark.parametrize("side", ["atlas", "sage"])
def test_partial_sum_never_matches(side):
    a, s = [atlas_row()], [sage_row()]
    if side == "atlas":
        a.append(atlas_row(Id="002", **{"Total charges projet (€)": None}))
    else:
        s.append(sage_row(**{"Charges (Dépenses)": None}))
    assert match_reconciliations(*frames(a, s)).iloc[0].match_status == "UNMATCHED"


@pytest.mark.parametrize("amount", [0, -1000])
def test_zero_and_negative(amount):
    row = match_reconciliations(*frames([atlas_row(**{"Total charges projet (€)": amount})], [sage_row(**{"Charges (Dépenses)": amount})])).iloc[0]
    assert row.match_rule == "MATCH_EXACT"
