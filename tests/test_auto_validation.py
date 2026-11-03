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
