import json

from matching_helpers import atlas_row, frames, sage_row
from reconciliation.exporters.review import export_review_bundle
from reconciliation.matching import match_reconciliations


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
