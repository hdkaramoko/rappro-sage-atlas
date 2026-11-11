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
                 sage_third_party_code="T", total_project_charges="100", currency="EUR", sage_bap_number="B")
    sage = dict(project_code="P", fiscal_year=2026, third_party="T", amount="100", ref="R",
                identity_complete=True, currency="EUR", matching_reference="B")
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
    {"amount": "101"}, {"amount": "-100"}, {"identity_complete": False}, {"matching_reference": "OTHER"},
    {"matching_reference": ""}, {"fiscal_year": 2025}])
def test_incompatible_proof_is_refused(change):
    """Projet, tiers, montant signé, BAP, période et identité restent obligatoires."""
    a, s = pair()
    changed = {**s, **change}
    with pytest.raises(ValueError):
        FuzzySafety([a], [changed]).verify(a, changed)


@pytest.mark.parametrize("label,rule", [
    ("JANVIER DUPONT FACTURE CONSULTANT", "MATCH_FUZZY_HIGH"),
    ("FACTURE CONSULTANT DUPONT FEVRIER", "MATCH_FUZZY_REVIEW")])
@pytest.mark.parametrize("competitor", [None, "sage", "atlas", "same_bap_sage", "same_bap_atlas"])
def test_real_export_checks_complete_sources(tmp_path, label, rule, competitor):
    """Le JSONL garde la règle fuzzy et n'autorise que les paires individuellement certaines.

    Un autre BAP ne bloque plus AUTO ; un même BAP concurrent reste bloquant.
    Le repli sans libellé est désactivé pour isoler les concurrents que le fuzzy
    n'a pas retenus. Seul tmp_path reçoit les fichiers.
    """
    left = [atlas_row(**{"Année": 2026, "Devise": "EUR"})]
    right = [sage_row(**{"Libellé pièce": label, "Journal": "ACH", "N° de ligne comptable": "1",
                        "N° de ligne Analytique": "1", "Devise": "EUR"})]
    if competitor in ("sage", "same_bap_sage"):
        right.append(sage_row(**{"Libellé pièce": "AUTRE", "Référence": "B" if competitor == "same_bap_sage" else "AUTRE", "Journal": "ACH",
                                "N° de ligne comptable": "2", "N° de ligne Analytique": "1"}))
    elif competitor in ("atlas", "same_bap_atlas"):
        left.append(atlas_row(Id="OTHER", **{"Année": 2026, "N° BAP (SAGE)": "B" if competitor == "same_bap_atlas" else "AUTRE", "Libellé ATLAS": "AUTRE"}))
    a, s = frames(left, right)
    from reconciliation.matching import MatchingConfig
    result = match_reconciliations(a, s, MatchingConfig(enable_without_label=False))
    path = export_review_bundle(a, s, result, tmp_path / "fuzzy.jsonl",
        controls=build_controls(a, s, result), include_sage_inventory=True)
    proposal = next(row for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())
                    if row.get("type") == "proposal" and row["atlas"][0]["Id"] == "001")
    assert proposal["rule"] == rule
    assert ("auto_validation" in proposal) == (competitor not in ("same_bap_sage", "same_bap_atlas"))


def test_original_currency_does_not_block_euro_charges():
    """Les devises d'origine différentes ne changent pas les charges déjà en euros."""
    a, s = pair()
    a["currency"], s["currency"] = "EUR - Euro", "XOF"
    FuzzySafety([a], [s]).verify(a, s)


@pytest.mark.parametrize("side", ["atlas", "sage"])
def test_unknown_bap_competitor_stays_blocking(side):
    """L'absence de BAP chez un concurrent ne prouve jamais qu'il est hors périmètre."""
    a, s = pair()
    left = [a, {**a, "source_id": "OTHER", "sage_bap_number": ""}] if side == "atlas" else [a]
    right = [s, {**s, "ref": "OTHER", "matching_reference": ""}] if side == "sage" else [s]
    with pytest.raises(ValueError, match="non unique"):
        FuzzySafety(left, right).verify(a, s)


@pytest.mark.parametrize("problem", [None, "shared", "document", "identity", "duplicate", "atlas", "sage", "date"])
def test_accounted_competitor_requires_distinct_identified_entry(problem):
    """Une pièce distincte prouvée libère seulement le contrôle explicitement activé."""
    a, s = pair()
    s = {**s, "document": "TARGET", "date": "2026-01-01"}
    accounted = {**a, "source_id": "C", "bap_status": "Comptabilisé", "sage_bap_number": "",
                 "total_sage_charges": "100", "sage_document_number": "OTHER", "accounting_date": "2026-02-01"}
    other = {**s, "ref": "OTHER", "document": "OTHER", "date": "2026-02-01", "matching_reference": "OTHER"}
    if problem == "shared":
        accounted.update(sage_document_number="TARGET", accounting_date="2026-01-01")
    if problem == "document":
        accounted["sage_document_number"] = ""
    if problem == "identity":
        other["identity_complete"] = False
    if problem == "date":
        accounted["accounting_date"] = ""
    left, right = [accounted, {**accounted, "source_id": "C2"}, a], [s, other]
    if problem == "duplicate":
        right.append(other.copy())
    if problem == "atlas":
        left.append({**a, "source_id": "CONCURRENT"})
    if problem == "sage":
        right.append({**s, "ref": "CONCURRENT"})
    guard = FuzzySafety(left, right)
    with pytest.raises(ValueError, match="non unique"):
        guard.verify(a, s)
    if problem is None:
        guard.verify(a, s, distinct_accounted=True)
    else:
        with pytest.raises(ValueError, match="non unique"):
            guard.verify(a, s, distinct_accounted=True)


def test_export_fuzzy_high_ignores_proven_distinct_accounted(tmp_path):
    """L'export réel autorise Libellé proche malgré une comptabilisée distincte."""
    left = [atlas_row(**{"Année": 2026}), atlas_row(**{
        "Id": "C", "Année": 2026, "Statut BAP": "Comptabilisé", "N° BAP (SAGE)": "",
        "N° pièce SAGE": "OTHER", "Date comptable": "2026-01-31", "Total charges SAGE (€)": "1000"})]
    right = [sage_row(**{"Libellé pièce": "JANVIER DUPONT FACTURE CONSULTANT", "Journal": "ACH",
                        "N° de ligne comptable": "1", "N° de ligne Analytique": "1"}),
             sage_row(**{"Numéro pièce": "OTHER", "Référence": "OTHER", "Journal": "ACH",
                         "N° de ligne comptable": "1", "N° de ligne Analytique": "1"})]
    a, s = frames(left, right)
    result = match_reconciliations(a, s)
    path = export_review_bundle(a, s, result, tmp_path / "distinct.jsonl",
                               controls=build_controls(a, s, result), include_sage_inventory=True)
    proposal = next(row for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())
                    if row.get("type") == "proposal" and row["atlas"][0]["Id"] == "001")
    assert proposal["rule"] == "MATCH_FUZZY_HIGH"
    assert proposal["auto_validation"]["state"] == "VALIDATED"
