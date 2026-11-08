"""Équilibre collectif des sommes signées, indépendant de la cardinalité."""

import pytest
from reconciliation_contract import control_identity, snapshot
from test_sage_inventory import calculate, record, source


@pytest.mark.parametrize("negative,total,state", [("-20", "100", "EQUILIBRE"), ("-19.99", "100", "EQUILIBRE"),
                                                  ("-19.98", "100", "ECART")])
def test_ods_multiple_signed_entries(negative, total, state):
    """Une ligne Atlas peut couvrir plusieurs écritures signées, avec tolérance au centime."""
    atlas = source(total, **{"N° pièce SAGE": "ODS-A", "Libellé SAGE": "Paie"})
    rows = [record("120", **{"Numéro pièce": "ODG-A", "Libellé pièce": "Paie"}),
            record(negative, **{"Numéro pièce": "ODG-B", "Libellé pièce": "Paie"})]
    result = calculate(atlas=[atlas], records=rows)
    assert result["state"] == state
    assert not result["reasons"]
    # Le snapshot utilisé hors contrôle collectif conserve son veto individuel.
    assert snapshot(control_identity(atlas), [atlas], [r["entry"] for r in rows],
                    amount_field="total_sage_charges")["status"] == "UNKNOWN"


def test_opposite_totals_do_not_balance_in_absolute_value():
    """Deux totaux opposés créent un écart signé, même si leurs valeurs absolues coïncident."""
    result = calculate(atlas=[source("100")], records=[record("-100")])
    assert result["state"] == "ECART"
    assert result["gap"] == "200.00"


def test_signed_group_keeps_duplicate_and_missing_guards():
    """Un doublon technique ou un montant absent reste indéterminé."""
    row = record("50")
    assert calculate(atlas=[source("100")], records=[row, row])["state"] == "INDETERMINE"
    assert calculate(atlas=[source(None)], records=[row])["state"] == "INDETERMINE"
