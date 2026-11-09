"""Recette AUTO fuzzy sur sources complètes et export réel, sans données privées."""

import json

import pytest

from matching_helpers import atlas_row, sage_row, frames
from reconciliation.exporters.review import export_review_bundle
from reconciliation.matching import match_reconciliations
from reconciliation.multiples import build_controls
from reconciliation_contract.fuzzy_safety import FuzzySafety


def pair():
    """Retourne une paire canonique certaine ; aucune entrée ni effet de bord externe."""
    atlas = dict(project_code="P", fiscal_year=2026, source_id="A", bap_status="Envoyé SAGE",
                 sage_third_party_code="T", total_project_charges="100", currency="EUR")
    sage = dict(project_code="P", fiscal_year=2026, third_party="T", amount="100", ref="R",
                identity_complete=True, currency="EUR")
    return atlas, sage


@pytest.mark.parametrize("side", ["atlas", "sage"])
def test_competitor_even_without_similar_label_blocks(side):
    """Un concurrent structuré bloque AUTO des deux côtés, quel que soit son libellé."""
    a, s = pair()
    left, right = [a], [s]
    if side == "atlas":
        left.append({**a, "source_id": "OTHER", "atlas_label": "Sans similarité"})
    else:
        right.append({**s, "ref": "OTHER", "label": "Sans similarité"})
    with pytest.raises(ValueError, match="non unique"):
        FuzzySafety(left, right).verify(a, s)


@pytest.mark.parametrize("change", [{"project_code": "Q"}, {"third_party": "OTHER"},
    {"amount": "101"}, {"amount": "-100"}, {"identity_complete": False}, {"currency": "USD"}, {"fiscal_year": 2025}])
def test_incompatible_proof_is_refused(change):
    """Projet, tiers, montant signé, devise, période et identité restent obligatoires."""
    a, s = pair()
    changed = {**s, **change}
    with pytest.raises(ValueError):
        FuzzySafety([a], [changed]).verify(a, changed)


@pytest.mark.parametrize("label,rule", [
    ("JANVIER DUPONT FACTURE CONSULTANT", "MATCH_FUZZY_HIGH"),
    ("FACTURE CONSULTANT DUPONT FEVRIER", "MATCH_FUZZY_REVIEW")])
@pytest.mark.parametrize("competitor", [None, "sage", "atlas"])
def test_real_export_checks_complete_sources(tmp_path, label, rule, competitor):
    """Le JSONL garde la règle fuzzy et n'autorise que les paires individuellement certaines.

    Les concurrents ont un autre BAP/libellé : candidate_count reste un, mais
    l'inventaire complet interdit AUTO. Seul tmp_path reçoit les fichiers.
    """
    left = [atlas_row(**{"Année": 2026, "Devise": "EUR"})]
    right = [sage_row(**{"Libellé pièce": label, "Journal": "ACH", "N° de ligne comptable": "1",
                        "N° de ligne Analytique": "1", "Devise": "EUR"})]
    if competitor == "sage":
        right.append(sage_row(**{"Libellé pièce": "AUTRE", "Référence": "AUTRE", "Journal": "ACH",
                                "N° de ligne comptable": "2", "N° de ligne Analytique": "1"}))
    elif competitor == "atlas":
        left.append(atlas_row(Id="OTHER", **{"Année": 2026, "N° BAP (SAGE)": "AUTRE", "Libellé ATLAS": "AUTRE"}))
    a, s = frames(left, right)
    result = match_reconciliations(a, s)
    path = export_review_bundle(a, s, result, tmp_path / "fuzzy.jsonl",
        controls=build_controls(a, s, result), include_sage_inventory=True)
    proposal = next(row for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())
                    if row.get("type") == "proposal" and row["atlas"][0]["Id"] == "001")
    assert proposal["rule"] == rule
    assert ("auto_validation" in proposal) == (competitor is None)
