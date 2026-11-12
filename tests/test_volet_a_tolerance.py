"""Frontières décimales du volet A et non-régression des autres seuils."""

import json
from decimal import Decimal
import pytest

from reconciliation_contract.fuzzy_safety import FuzzySafety
from reconciliation_contract.matching_policy import MATCHING_TOLERANCES, rule_tolerance
from matching_helpers import atlas_row, sage_row, frames
from reconciliation.matching import match_reconciliations
from reconciliation.exporters.review import export_review_bundle
from reconciliation.multiples import build_controls


@pytest.mark.parametrize("difference,allowed", [("0.0116", True), ("0.0500", True), ("0.0501", False)])
@pytest.mark.parametrize("rule", ["MATCH_BAP", "MATCH_INDIVIDUAL"])
def test_guard_exact_source_boundary(rule, difference, allowed):
    """Les deux recours utilisent la différence source exacte, avec borne inclusive à 0,05."""
    a = dict(project_code="P", fiscal_year=2026, source_id="A", bap_status="Envoyé SAGE",
        sage_third_party_code="T", sage_bap_number="B", total_project_charges=str(Decimal("100") + Decimal(difference)))
    s = dict(project_code="P", fiscal_year=2026, third_party="T", matching_reference="B", ref="R", amount="100", identity_complete=True)
    guard = FuzzySafety([a], [s], precise_atlas=[a])
    check = guard.verify_bap_balance if rule == "MATCH_BAP" else guard.verify_individual
    if allowed:
        check(a, s, tolerance=rule_tolerance(rule, MATCHING_TOLERANCES), precise=True)
    else:
        with pytest.raises(ValueError):
            check(a, s, tolerance=rule_tolerance(rule, MATCHING_TOLERANCES), precise=True)


@pytest.mark.parametrize("rule", ["MATCH_EXACT", "MATCH_AMOUNT", "MATCH_CONFIRMED_ATLAS", "MATCH_FUZZY_HIGH", "MATCH_FUZZY_REVIEW", "MATCH_WITHOUT_LABEL"])
def test_other_rules_keep_one_cent(rule):
    """La déclaration des deux recours ne modifie aucun autre seuil ni le repli ancien."""
    assert rule_tolerance(rule, MATCHING_TOLERANCES) == Decimal("0.01")
    assert rule_tolerance("MATCH_BAP") == Decimal("0.01")


@pytest.mark.parametrize("policy", [{"MATCH_EXACT": "0.05"}, {"MATCH_BAP": "0.06"}, {"MATCH_INDIVIDUAL": 0.05}])
def test_policy_cannot_expand_other_rules_or_unknown_thresholds(policy):
    """Le contrat refuse tout élargissement global ou seuil non explicitement reconnu."""
    with pytest.raises(ValueError, match="non reconnues"):
        rule_tolerance("MATCH_BAP", policy)


@pytest.mark.parametrize("amount,authorized", [("362.2616", True), ("362.3000", True), ("362.3001", False)])
def test_real_individual_export_preserves_precision(tmp_path, amount, authorized):
    """Le vrai export individuel accepte 0,05 sans arrondir un écart de 0,0501."""
    a, s = frames([atlas_row(**{"Année": 2026, "Total charges projet (€)": amount})],
        [sage_row(**{"Charges (Dépenses)": value, "Journal": "ACH", "N° de ligne comptable": str(number),
                     "N° de ligne Analytique": "1"}) for number, value in enumerate(("362.25", "50"), 1)])
    result = match_reconciliations(a, s)
    path = export_review_bundle(a, s, result, tmp_path / "individual.jsonl", controls=build_controls(a, s, result), include_sage_inventory=True)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    proposal = next(r for r in records if r.get("type") == "proposal")
    assert bool(proposal.get("auto_validation")) == authorized
    assert proposal["matching_source_amounts"]["001"] == amount


def test_complete_bap_drift_cannot_become_individual_auto(tmp_path):
    """Deux écarts de 0,03 restent manuels : ni BAP ni son repli ne contournent 0,05 global."""
    from examples.volet_a_fixture import generate
    path = generate(tmp_path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    drifts = [r for r in records if r.get("type") == "proposal" and any(a["Id"] == "D1" for a in r["atlas"])]
    assert len(drifts) == 1 and drifts[0]["rule"] == "MATCH_BAP"
    assert not drifts[0].get("auto_validation")
