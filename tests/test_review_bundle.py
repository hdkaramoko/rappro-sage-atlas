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
    assert records[-1] == {"complete": 1}
    assert [row["Id"] for row in records[0]["atlas"]] == ["A", "B"]
    assert records[0]["sage_total"] == 1000
    assert records[0]["evidence"][0]["rows"][0]["Projet"] == "P"
    assert records[0]["evidence"][0]["rows"][0]["Numéro pièce"] == "DOC-01"
