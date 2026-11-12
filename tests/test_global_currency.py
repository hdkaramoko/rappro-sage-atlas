"""Devise d'origine indépendante des colonnes de charges EUR du contrôle global."""

import pytest
from test_sage_inventory import calculate, record, source


@pytest.mark.parametrize("currency", ["XOF - Franc CFA", "USD", "EUR - Euro", ""])
@pytest.mark.parametrize("amount", ["372.41", "-372.41"])
def test_original_currency_does_not_make_balanced_charges_indeterminate(currency, amount):
    """Une charge EUR équilibrée, y compris un avoir, reste équilibrée quelle que soit la devise d'origine."""
    result = calculate(atlas=[source(amount, Devise=currency)], records=[record(amount, Devise="XOF")])
    assert result["state"] == result["accounted_state"] == "EQUILIBRE"
    assert result["gap"] == "0.00"
    assert not result["reasons"]


def test_currency_removal_does_not_hide_amount_difference():
    """Un véritable écart financier reste ECART après suppression du seul veto de devise."""
    result = calculate(atlas=[source("-370", Devise="XOF")], records=[record("-372.41", Devise="XOF")])
    assert result["state"] == "ECART"
    assert result["gap"] == "2.41"


def test_currency_removal_keeps_identity_and_missing_amount_guards():
    """La suppression du motif de devise ne blanchit ni collisions ni montants absents."""
    assert calculate(atlas=[source("10000", Devise="XOF")], records=[record("6000"), record("4000")])["state"] == "INDETERMINE"
    assert calculate(atlas=[source(None, Devise="XOF")])["state"] == "INDETERMINE"
