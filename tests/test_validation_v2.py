"""Bijection Exact et autorisations exportées par le vrai moteur."""

import copy
import json
import pytest
from matching_helpers import atlas_row, sage_row, frames
from reconciliation import config
from reconciliation.matching import match_reconciliations
from reconciliation.exporters.review import export_review_bundle
from reconciliation.multiples import build_controls
from reconciliation_contract import entry_from_sage
from reconciliation_contract.exact_assignment import exact_bijection


def sources(amounts=("652.40", "36.48")):
    """Construit des sources Exact complètes avec références d'écritures distinctes."""
    atlas, sage = [], []
    for index, amount in enumerate(amounts, 1):
        atlas.append(atlas_row(**{"Id": str(index), "Année": 2026, "Total charges projet (€)": amount, "Devise": "EUR"}))
        proof = sage_row(**{"Charges (Dépenses)": amount, "Journal": "ACH", "N° de ligne comptable": str(index),
                            "N° de ligne Analytique": "1", "Devise": "EUR"})
        proof["entry_ref"] = entry_from_sage(proof)["ref"]
        sage.append(proof)
    return atlas, sage


def test_unique_bijection_and_order():
    """Deux montants distincts donnent la même bijection quelle que soit la permutation."""
    atlas, sage = sources()
    result = exact_bijection(atlas, sage)
    assert result == exact_bijection(atlas[::-1], sage[::-1])
    assert len({e["ref"] for e in result.values()}) == 2


@pytest.mark.parametrize("field,value", [
    ("Projet", "OTHER"), ("Référence", "OTHER"), ("Code Tiers - Tiers doc Orig", "OTHER"),
    ("Libellé pièce", "OTHER"), ("Date comptable", "2025-01-31"), ("N° de ligne Analytique", ""),
    ("Charges (Dépenses)", "-652.40"), ("Charges (Dépenses)", "653.40")])
def test_incompatible_entry_blocks_group(field, value):
    """Une incohérence de clé, signe, année ou montant empêche toute attribution collective."""
    atlas, sage = sources()
    sage[0][field] = value
    sage[0]["entry_ref"] = entry_from_sage(sage[0])["ref"]
    with pytest.raises(ValueError):
        exact_bijection(atlas, sage)


def test_repeated_amount_or_reference_never_picks_arbitrarily():
    """Les répétitions créant plusieurs appariements et les références dupliquées sont refusées."""
    atlas, sage = sources(("652.40", "652.40"))
    with pytest.raises(ValueError):
        exact_bijection(atlas, sage)
    atlas, sage = sources()
    with pytest.raises(ValueError):
        exact_bijection(atlas, [sage[0], copy.deepcopy(sage[0])])


@pytest.mark.parametrize("amounts,authorized", [(("652.40", "36.48"), True), (("652.40", "652.40"), False)])
def test_real_engine_exports_authorization_only_for_unique_group(tmp_path, monkeypatch, amounts, authorized):
    """Le contrat v3 n'autorise le groupe moteur Exact que si sa bijection est démontrée."""
    monkeypatch.setattr(config, "AUTO_VALIDATION", {"enabled": True, "statuses": ["MATCH_EXACT"]})
    atlas, sage = sources(amounts)
    a, s = frames(atlas, sage)
    result = match_reconciliations(a, s)
    assert result.iloc[0].match_rule == "MATCH_EXACT"
    path = export_review_bundle(a, s, result, tmp_path / "group.jsonl", year=2026,
                               controls=build_controls(a, s, result), include_sage_inventory=True)
    records = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["validation_policy"] == "confirmed-exact-v2"
    proposal = next(r for r in records if r.get("type") == "proposal")
    assert ("auto_validation" in proposal) == authorized
    assert str(proposal["sage_total"]) != str(amounts[0]) or not authorized


def test_xof_original_currency_keeps_eur_exact_authorization(tmp_path, monkeypatch):
    """1691538/1691539 : les charges EUR concordent malgré la devise d'origine XOF."""
    monkeypatch.setattr(config, "AUTO_VALIDATION", {"enabled": True, "statuses": ["MATCH_EXACT"]})
    atlas, sage = sources(("3926.2706", "35.5282"))
    for row, identifier in zip(atlas, ("1691538", "1691539")):
        row.update({"Id": identifier, "Devise": "XOF - Franc CFA"})
    for row, amount in zip(sage, ("3926.27", "35.53")):
        row.update({"Devise": "XOF", "Charges (Dépenses)": amount, "Montant en devises": "2598770"})
    a, s = frames(atlas, sage)
    result = match_reconciliations(a, s)
    path = export_review_bundle(a, s, result, tmp_path / "xof.jsonl", year=2026,
                               controls=build_controls(a, s, result), include_sage_inventory=True)
    proposal = next(r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r.get("type") == "proposal")
    assert proposal["auto_validation"]["rule"] == "MATCH_EXACT"
    mapping = exact_bijection(proposal["atlas"], [r for c in proposal["evidence"] for r in c["rows"]])
    assert mapping["1691538"]["amount"] == "3926.27"
    assert mapping["1691539"]["amount"] == "35.53"
