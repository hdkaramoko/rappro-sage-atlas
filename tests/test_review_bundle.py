import json
import pytest

from reconciliation import config

from matching_helpers import atlas_row, frames, sage_row
from reconciliation.exporters.review import export_review_bundle
from reconciliation.matching import match_reconciliations


@pytest.fixture(autouse=True)
def legacy_diagnostic_mode(monkeypatch):
    """Exerce explicitement les exports v2 historiques sans activation collective."""
    monkeypatch.setattr(config, "PIECE_COHERENCE", {"enabled": True, "mode": "DIAGNOSTIC"})


def test_validation_context_is_preserved_in_inventory_and_proposals(tmp_path):
    """Les nombres français sont normalisés sans perdre zéro ni précision."""
    a, s = frames([atlas_row(**{
        "Année": 2026, "Montant refacturables": "0",
        "Prix unitaire prévu": "1 234,123456", "Nombre d'unités": "2,5",
    })])
    from reconciliation.multiples import build_controls
    result = match_reconciliations(a, s)
    for version in (2, 3):
        controls = build_controls(a, s, result) if version == 3 else None
        path = export_review_bundle(a, s, result, tmp_path / f"v{version}.jsonl", controls=controls)
        records = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
        inventory = next(r["atlas"] for r in records if r.get("type") == "inventory")
        source = next(r["atlas"][0] for r in records if r.get("type") == "proposal")
        for row in (inventory, source):
            assert row["Montant refacturables"] == "0"
            assert row["Prix unitaire prévu"] == "1234.123456"
            assert row["Nombre d'unités"] == "2.5"


def test_bundle_contains_individual_sources_and_complete_sage_evidence(tmp_path):
    a, s = frames([atlas_row(Id="A", **{"Total charges projet (€)": 400}),
                   atlas_row(Id="B", **{"Total charges projet (€)": 600})],
                  [sage_row(Projet="OTHER"), sage_row()])
    result = match_reconciliations(a, s)
    path = export_review_bundle(a, s, result, tmp_path / "review.jsonl")
    records = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["schema_version"] == 2
    assert records[-1] == {"complete": 1, "inventory_count": 2}
    record = next(row for row in records if row.get("type") == "proposal")
    assert [row["Id"] for row in record["atlas"]] == ["A", "B"]
    assert record["sage_total"] == 1000
    assert record["evidence"][0]["rows"][0]["Projet"] == "P"
    assert record["evidence"][0]["rows"][0]["Numéro pièce"] == "DOC-01"


def test_inventory_includes_accounted_lines_and_both_amounts(tmp_path):
    a, s = frames([atlas_row(Id="A", **{"Année": 2026}),
                   atlas_row(Id="B", **{"Année": 2026, "Statut BAP": "Comptabilisé", "Total charges SAGE (€)": 900})])
    path = export_review_bundle(a, s, match_reconciliations(a, s), tmp_path / "campaign.jsonl",
                               campaign_name="Septembre", scope="complet")
    records = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    inventory = [row["atlas"] for row in records if row.get("type") == "inventory"]
    assert records[0]["name"] == "Septembre"
    assert len(inventory) == 2
    assert inventory[1]["Statut BAP"] == "Comptabilisé"
    assert inventory[1]["Total charges SAGE (€)"] == 900
    assert records[-1] == {"complete": 1, "inventory_count": 2}
