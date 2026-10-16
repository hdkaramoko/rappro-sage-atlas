import json

import pytest

from reconciliation_contract.piece_coherence import atlas_entry, sage_entry, check_piece, validate_check


def atlas(identifier="A", amount="100", **changes):
    return {"Id": identifier, "Code projet": "P", "Année": 2026,
            "N° pièce SAGE": "D", "Date comptable": "2026-01-01",
            "Code tiers SAGE": "T", "N° BAP (SAGE)": "B",
            "Total charges SAGE (€)": amount, "Statut BAP": "Envoyé SAGE", **changes}


def sage(line="1", amount="100", **changes):
    return {"Projet": "P", "Numéro pièce": "D", "Date comptable": "2026-01-01",
            "Code Tiers - Tiers doc Orig": "T", "Référence": "B", "Journal": "ACH",
            "N° de ligne comptable": line, "N° de ligne Analytique": "1",
            "Charges (Dépenses)": amount, **changes}


def check(left=None, right=None):
    return check_piece("P", "D", [atlas_entry(r) for r in (left if left is not None else [atlas()])],
                       [sage_entry(r) for r in (right if right is not None else [sage()])])


def test_unique_piece_normalization_and_signed_decimals():
    result = check([atlas(amount="-100.005", **{"Code tiers SAGE": " t\u00a0", "N° BAP (SAGE)": " b "})],
                   [sage(amount="-100.015")])
    assert result["status"] == "PIECE_RECONCILED"
    assert result["gap"] == "0.010"
    assert validate_check(result) == result


def test_shared_piece_does_not_group_by_date():
    result = check([atlas("A", "40"), atlas("B", "60", **{"Date comptable": "2026-02-01"})],
                   [sage("1", "40"), sage("2", "60", **{"Date comptable": "2026-03-01"})])
    assert result["status"] == "PIECE_RECONCILED"
    assert result["atlas_count"] == 2


def test_legitimate_repeated_combinations_need_equal_multiplicity():
    left = [atlas("A", "50"), atlas("B", "50")]
    assert check(left, [sage("1", "50"), sage("2", "50")])["status"] == "PIECE_RECONCILED"
    result = check(left, [sage("1", "100")])
    assert result["gap"] == "0"
    assert result["individual_status"] == "MISMATCH"


@pytest.mark.parametrize("changes,status", [
    ({"Référence": "OTHER"}, "PIECE_MISMATCH"),
    ({"Code Tiers - Tiers doc Orig": "OTHER"}, "PIECE_MISMATCH"),
    ({"Référence": None}, "PIECE_AMBIGUOUS"),
    ({"Code Tiers - Tiers doc Orig": None}, "PIECE_AMBIGUOUS"),
    ({"N° de ligne Analytique": None}, "PIECE_AMBIGUOUS"),
    ({"Charges (Dépenses)": "101"}, "PIECE_MISMATCH"),
    ({"Charges (Dépenses)": None}, "NOT_CHECKED"),
    ({"Date comptable": "2025-01-01"}, "NOT_CHECKED"),
])
def test_mismatch_versus_insufficient_data(changes, status):
    assert check(right=[sage(**changes)])["status"] == status


def test_absent_sage_piece_and_duplicate_identity():
    assert check(right=[])["status"] == "PIECE_MISMATCH"
    assert check([atlas("A", "50"), atlas("B", "50")],
                 [sage("1", "50"), sage("1", "50")])["status"] == "PIECE_AMBIGUOUS"


def test_equal_totals_do_not_hide_individual_or_sign_conflicts():
    assert check([atlas("A", "100"), atlas("B", "-40")],
                 [sage("1", "90"), sage("2", "-30")])["status"] == "PIECE_MISMATCH"
    assert check([atlas("A", "100"), atlas("B", "-40")],
                 [sage("1", "100"), sage("2", "-40")])["status"] == "PIECE_RECONCILED"
    assert check([atlas(amount="-0.004")], [sage(amount="0.004")])["status"] == "PIECE_MISMATCH"


def test_diagnostic_cannot_be_tampered_with():
    result = check()
    result["status"] = "PIECE_MISMATCH"
    with pytest.raises(ValueError):
        validate_check(result)


def test_export_diagnostic_does_not_change_auto_requests(tmp_path, monkeypatch):
    from matching_helpers import frames
    from reconciliation import config
    from reconciliation.matching import match_reconciliations
    from reconciliation.exporters.review import export_review_bundle
    a, s = frames([atlas(**{"Total charges projet (€)": 100})], [sage()])
    result = match_reconciliations(a, s)
    proposals = []
    for enabled in (True, False):
        monkeypatch.setattr(config, "PIECE_COHERENCE", {"enabled": enabled, "mode": "DIAGNOSTIC"})
        path = export_review_bundle(a, s, result, tmp_path / "diagnostic.jsonl")
        proposal = next(r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r.get("type") == "proposal")
        if enabled:
            assert proposal.pop("piece_coherence")["status"] == "PIECE_RECONCILED"
        else:
            assert "piece_coherence" not in proposal
        proposals.append(proposal)
    assert proposals[0] == proposals[1]


def test_builder_isolates_projects_and_refuses_activation(monkeypatch):
    from matching_helpers import frames
    from reconciliation import config
    from reconciliation.piece_coherence import build_piece_checks
    a, s = frames([atlas()], [sage(Projet="OTHER")])
    assert build_piece_checks(a, s)[("P", "D")]["status"] == "PIECE_MISMATCH"
    monkeypatch.setattr(config, "PIECE_COHERENCE", {"enabled": True, "mode": "ACTIVE"})
    with pytest.raises(ValueError, match="DIAGNOSTIC"):
        build_piece_checks(a, s)


def test_builder_refuses_uncertain_sage_perimeter():
    from matching_helpers import frames
    from reconciliation.piece_coherence import build_piece_checks
    a, s = frames([atlas()], [sage(), sage("2", **{"Numéro pièce": None})])
    assert build_piece_checks(a, s)[("P", "D")]["status"] == "NOT_CHECKED"
