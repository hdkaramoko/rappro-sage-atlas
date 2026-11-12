import pytest
from reconciliation import config
from reconciliation.auto_validation import proposal_metadata, validate_config


def record(**changes):
    return dict(match_status="MATCHED", match_rule="MATCH_EXACT", requires_review=False,
                atlas_row_count=1, candidate_count=1, sage_row_count=1,
                cardinality_match=True, amount_difference=0, reason="UNIQUE_CANDIDATE",
                sage_document_number="D", sage_accounting_date="2026-01-01") | changes


def test_configuration(monkeypatch):
    monkeypatch.setattr(config, "AUTO_VALIDATION", {"enabled": True, "statuses": ["MATCHED_EXACT"]})
    with pytest.raises(ValueError, match="inconnus"):
        validate_config()


@pytest.mark.parametrize("amount,gap,allowed", [(13253.92, -0.010000000000218279, True),
    (13253.93, -0.020000000000436557, False), (None, 0, False)])
def test_decimal_boundary_for_exact(amount, gap, allowed):
    """Les montants décimaux admettent un centime exact, jamais deux ou une absence."""
    row = record(atlas_amount=13253.91, sage_amount=amount, amount_difference=gap)
    assert bool(proposal_metadata(row, {"enabled": True, "statuses": ["MATCH_EXACT"]})) == allowed


def test_export_exact_group_uses_decimal_source_sums(tmp_path):
    """Un groupe Exact à un centime d'écart garde AUTO malgré les résidus de sommes.

    Exerce le vrai matching, la bijection et l'export v3 sur deux lignes de
    chaque source. Seul le dossier temporaire reçoit le JSONL synthétique.
    """
    import json
    from matching_helpers import atlas_row, sage_row, frames
    from reconciliation.exporters.review import export_review_bundle
    from reconciliation.matching import match_reconciliations
    from reconciliation.multiples import build_controls
    a, s = frames([atlas_row(Id=str(i), **{"Année": 2026, "Total charges projet (€)": amount})
                   for i, amount in enumerate((0.1, 0.2))],
                  [sage_row(**{"Charges (Dépenses)": amount, "Journal": "ACH",
                               "N° de ligne comptable": str(i), "N° de ligne Analytique": "1"})
                   for i, amount in enumerate((0.09, 0.2))])
    result = match_reconciliations(a, s)
    assert abs(result.iloc[0].amount_difference) > 0.01
    path = export_review_bundle(a, s, result, tmp_path / "decimal.jsonl", controls=build_controls(a, s, result))
    payload = next(r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r.get("type") == "proposal")
    assert payload["auto_validation"]["rule"] == "MATCH_EXACT"


@pytest.mark.parametrize("options", [{"enabled": False, "statuses": ["MATCH_EXACT"]},
                                      {"enabled": True, "statuses": []},
                                      {"enabled": True, "statuses": ["MATCH_CONFIRMED_ATLAS"]}])
def test_no_authorization(options):
    assert proposal_metadata(record(), options) is None


def test_final_safety():
    options = {"enabled": True, "statuses": ["MATCHED"]}
    assert proposal_metadata(record(), options)["source"] == "AUTO"
    for field, value in [("match_status", "AMBIGUOUS"), ("requires_review", True),
                         ("atlas_row_count", 2), ("sage_row_count", 2),
                         ("amount_difference", 10), ("candidate_count", 2),
                         ("reason", "INCOMPLETE_SAGE_EVIDENCE"),
                         ("match_rule", "UNMATCHED")]:
        row = record()
        row[field] = value
        assert proposal_metadata(row, options) is None


@pytest.mark.parametrize("rule", ["MATCH_AMOUNT", "MATCH_FUZZY_HIGH", "MATCH_FUZZY_REVIEW", "MATCH_WITHOUT_LABEL"])
def test_configured_rule_overrides_only_experimental_review(rule):
    row = record(match_rule=rule, requires_review=True)
    options = {"enabled": True, "statuses": [rule]}
    assert proposal_metadata(row, options)["rule"] == rule
    assert proposal_metadata(row, {"enabled": True, "statuses": ["MATCH_EXACT"]}) is None
    for changes in ({"reason": "INCOMPLETE_SAGE_EVIDENCE"}, {"match_status": "AMBIGUOUS"},
                    {"candidate_count": 2}, {"atlas_row_count": 2}, {"amount_difference": float("nan")},
                    {"sage_document_number": None}):
        assert proposal_metadata(row | changes, options) is None


def test_amount_real_multiple_sage_rows(tmp_path, monkeypatch):
    """Le contrat v2 conserve les métadonnées sans activer le contrôle collectif v3."""
    monkeypatch.setattr(config, "PIECE_COHERENCE", {"enabled": True, "mode": "DIAGNOSTIC"})
    import json
    from matching_helpers import atlas_row, sage_row, frames
    from reconciliation.exporters.review import export_review_bundle
    from reconciliation.matching import match_reconciliations
    a, s = frames([atlas_row()], [sage_row(**{"Charges (Dépenses)": 400}),
                                  sage_row(**{"Charges (Dépenses)": 600})])
    result = match_reconciliations(a, s)
    assert result.iloc[0].match_rule == "MATCH_AMOUNT"
    monkeypatch.setattr(config, "AUTO_VALIDATION", {"enabled": True, "statuses": ["MATCH_AMOUNT"]})
    path = export_review_bundle(a, s, result, tmp_path / "amount.jsonl")
    payload = next(r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r.get("type") == "proposal")
    assert payload["auto_validation"]["rule"] == "MATCH_AMOUNT"


def test_fuzzy_real_result_requires_explicit_authorization():
    from matching_helpers import sage_row, frames
    from reconciliation.matching import match_reconciliations
    row = match_reconciliations(*frames(sage=[sage_row(**{
        "Libellé pièce": "JANVIER DUPONT FACTURE CONSULTANT"})])).iloc[0].to_dict()
    assert row["match_rule"] == "MATCH_FUZZY_HIGH" and row["requires_review"]
    assert proposal_metadata(row, {"enabled": True, "statuses": ["MATCH_FUZZY_HIGH"]})
    assert proposal_metadata(row, {"enabled": True, "statuses": ["MATCH_EXACT"]}) is None


def test_jsonl_metadata_is_optional(tmp_path, monkeypatch):
    """Le JSONL historique v2 publie l'autorisation uniquement si configurée."""
    monkeypatch.setattr(config, "PIECE_COHERENCE", {"enabled": True, "mode": "DIAGNOSTIC"})
    import json
    from matching_helpers import atlas_row, frames
    from reconciliation.exporters.review import export_review_bundle
    from reconciliation.matching import match_reconciliations
    a, s = frames([atlas_row()])
    result = match_reconciliations(a, s)
    for enabled in (False, True):
        monkeypatch.setattr(config, "AUTO_VALIDATION", {"enabled": enabled, "statuses": ["MATCH_EXACT"]})
        path = export_review_bundle(a, s, result, tmp_path / "bundle.jsonl")
        proposal = next(r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())
                        if r.get("type") == "proposal")
        assert ("auto_validation" in proposal) == enabled


def test_confirmed_export_uses_sage_charges_despite_project_gap(tmp_path):
    """Les deux Confirmé d'une pièce de 868,19 EUR reçoivent l'autorisation AUTO.

    Les charges projet 753,63 restent sources ; les charges Sage 758,63 sont
    la référence. Les autres catégories conservent leur veto d'écart projet.
    """
    import json
    import pandas as pd
    from matching_helpers import atlas_row, sage_row, frames
    from reconciliation.exporters.review import export_review_bundle
    from reconciliation.matching import match_reconciliations
    from reconciliation.multiples import build_controls
    atlas, sage = frames([
        atlas_row(Id="A", **{"Année": 2026, "Date comptable": pd.Timestamp("2026-01-31"),
                             "N° pièce SAGE": "DOC-01", "Total charges projet (€)": 109.56, "Total charges SAGE (€)": 109.56}),
        atlas_row(Id="B", **{"Année": 2026, "Date comptable": pd.Timestamp("2026-01-31"),
                             "N° pièce SAGE": "DOC-01", "Total charges projet (€)": 753.63, "Total charges SAGE (€)": 758.63})],
        [sage_row(**{"Charges (Dépenses)": amount, "N° de ligne comptable": str(i),
                     "N° de ligne Analytique": "1", "Journal": "ACH"}) for i, amount in enumerate((109.56, 758.63), 1)])
    result = match_reconciliations(atlas, sage)
    path = export_review_bundle(atlas, sage, result, tmp_path / "confirmed.jsonl", controls=build_controls(atlas, sage, result))
    proposals = [r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r.get("type") == "proposal"]
    assert len(proposals) == 2
    assert all(p["auto_validation"]["rule"] == "MATCH_CONFIRMED_ATLAS" for p in proposals)
    assert all(p["piece_coherence"]["status"] == "PIECE_RECONCILED" for p in proposals)
    assert proposals[1]["atlas"][0]["Total charges projet (€)"] == 753.63
    assert proposal_metadata(record(amount_difference=5), {"enabled": True, "statuses": ["MATCH_EXACT"]}) is None


@pytest.mark.parametrize("amount", [None, "NaN", "Infinity"])
def test_confirmed_missing_sage_amount_never_authorizes(amount):
    """Les Confirmé sans charge Sage finie ne sont jamais autorisés automatiquement."""
    row = record(match_rule="MATCH_CONFIRMED_ATLAS", reason="ATLAS_EVIDENCE_PRESENT", sage_amount=amount)
    assert proposal_metadata(row, {"enabled": True, "statuses": ["MATCH_CONFIRMED_ATLAS"]}) is None
