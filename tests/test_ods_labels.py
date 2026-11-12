"""Séparation des libellés de recherche Atlas et de contrôle comptable ODS/ODG."""

import json
import pandas as pd
import pytest
from reconciliation_contract import control_identity, entry_from_sage, snapshot, ODS_LABEL_POLICY
from reconciliation.exporters.review import export_review_bundle
from reconciliation.multiples import build_controls, inventory_rows
from reconciliation.matching import match_reconciliations
from matching_helpers import frames, atlas_row as sent_row, sage_row as matching_sage
from test_multiples import atlas_row, sage_row


def accounted(sage_label):
    """Construit un ODS comptabilisé avec libellé Atlas volontairement différent."""
    return atlas_row(**{"N° pièce SAGE": "ODS-ATLAS", "Libellé ATLAS": "Texte de recherche Atlas",
                        "Libellé SAGE": sage_label, "Total charges SAGE (€)": "100"})


def test_accounted_ods_identity_uses_sage_label_and_preserves_both_sources():
    """Le texte Sage du fichier Atlas rejoint le libellé pièce Sage après normalisation commune."""
    raw = accounted("Réaffect auto salaires 08/26")
    source = next(inventory_rows(pd.DataFrame([raw])))
    entry = entry_from_sage(sage_row(**{"Numéro pièce": "ODG-SAGE", "Libellé pièce": "REAFFECT  AUTO SALAIRES 08/26"}))
    assert control_identity(source) == control_identity(entry, sage=True)
    assert source["atlas_label"] == "Texte de recherche Atlas"
    assert source["sage_label"] == "Réaffect auto salaires 08/26"
    assert snapshot(control_identity(source), [source], [entry], amount_field="total_sage_charges")["status"] == "BALANCED"


@pytest.mark.parametrize("sage_label", [None, "", "   "])
def test_missing_sage_label_is_reported_without_atlas_fallback(sage_label):
    """Un libellé Sage vide reste vide dans la clé et bloque le contrôle, même avec un texte Atlas."""
    source = next(inventory_rows(pd.DataFrame([accounted(sage_label)])))
    key = control_identity(source)
    assert key["parts"][-1] == ""
    result = snapshot(key, [source], [], amount_field="total_sage_charges")
    assert result["status"] == "UNKNOWN"
    assert "Libellé SAGE Atlas absent pour le contrôle ODS/ODG" in result["reasons"]


def test_sent_matching_still_uses_atlas_label_with_different_sage_label():
    """La proposition Exact Envoyé reste fondée sur Libellé ATLAS, jamais sur Libellé SAGE."""
    a, s = frames([sent_row(**{"Année": 2026, "Libellé SAGE": "Autre texte comptable"})], [matching_sage()])
    result = match_reconciliations(a, s)
    assert result.iloc[0].match_rule == "MATCH_EXACT"
    source = next(inventory_rows(a))
    source["sage_document_number"] = "ODS-TEST"
    assert control_identity(source)["parts"][-1] == "facture consultant dupont janvier"


def test_old_canonical_source_keeps_historical_identity():
    """L'absence historique de sage_label ne réinterprète pas une clé déjà signée."""
    source = next(inventory_rows(pd.DataFrame([accounted("Nouveau texte")])))
    source.pop("sage_label")
    assert control_identity(source)["parts"][-1] == "texte de recherche atlas"


def test_v3_exports_sage_label_and_policy_without_changing_matching(tmp_path):
    """Le vrai moteur/exporteur conserve les deux libellés dans le nouveau JSONL v3."""
    a, s = frames([accounted("Réaffect salaires")], [sage_row(**{
        "Numéro pièce": "ODG-SAGE", "Libellé pièce": "Réaffect salaires"})])
    result = match_reconciliations(a, s)
    path = export_review_bundle(a, s, result, tmp_path / "ods.jsonl", year=2026,
                               controls=build_controls(a, s, result), include_sage_inventory=True)
    records = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["ods_label_policy"] == ODS_LABEL_POLICY
    inventory = next(row["atlas"] for row in records if row.get("type") == "inventory")
    assert inventory["Libellé SAGE"] == "Réaffect salaires"
    control = next(row["data"] for row in records if row.get("type") == "control")
    assert control["status"] == "BALANCED"
    assert control["atlas"][0]["sage_label"] == "Réaffect salaires"
