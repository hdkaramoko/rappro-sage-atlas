import pytest
from reconciliation import config
from reconciliation.auto_validation import proposal_metadata, validate_config


def record(**changes):
    return dict(match_status="MATCHED", match_rule="MATCH_EXACT", requires_review=False,
                atlas_row_count=1, candidate_count=1, sage_row_count=1,
                cardinality_match=True, amount_difference=0, **changes)


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
                         ("match_rule", "MATCH_FUZZY_HIGH")]:
        row = record()
        row[field] = value
        assert proposal_metadata(row, options) is None


def test_jsonl_metadata_is_optional(tmp_path, monkeypatch):
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
