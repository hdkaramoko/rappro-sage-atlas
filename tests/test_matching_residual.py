"""Recette des recours finaux sur identités réelles de preuves synthétiques."""

import json

from examples.matching_bap_fixture import frames, generate
from reconciliation.matching import match_reconciliations, MatchingConfig
from reconciliation import config


def test_bap_bijection_and_individual_are_additive(tmp_path):
    """Le témoin conserve Sans libellé et récupère deux BAP plus un individuel uniques."""
    summary = generate(tmp_path)
    assert summary["before"]["auto_lines"] == 0
    assert summary["after"]["auto_lines"] == 4
    assert summary["after"]["atlas_lines"] == 6
    proposals = [r for r in map(json.loads, (tmp_path / "after.jsonl").read_text(encoding="utf-8").splitlines()) if r.get("type") == "proposal"]
    by_id = {a["Id"]: p for p in proposals for a in p["atlas"]}
    for identifier in ("1681313", "1681314"):
        assert by_id[identifier]["rule"] == "MATCH_BAP"
        assert by_id[identifier]["auto_validation"]
        assert len(by_id[identifier]["evidence"][0]["rows"]) == 1
    refs = [by_id[i]["evidence"][0]["rows"][0]["entry_ref"] for i in ("1681313", "1681314")]
    assert len(set(refs)) == 2
    assert by_id["I"]["rule"] == "MATCH_INDIVIDUAL"
    assert "auto_validation" not in by_id["R1"]
    assert by_id["R1"]["key"] == by_id["R2"]["key"]


def test_priority_sources_and_trace_are_preserved():
    """Les matches antérieurs, les sources et les deux nouvelles étapes restent traçables."""
    atlas, sage = frames()
    original_a, original_s = atlas.copy(deep=True), sage.copy(deep=True)
    before = match_reconciliations(atlas, sage, MatchingConfig(enable_residual=False))
    after = match_reconciliations(atlas, sage, collect_trace=True)
    old = before[before.match_status == "MATCHED"].iloc[0]
    new = after[after.atlas_group_id == old.atlas_group_id].iloc[0]
    assert old.candidate_ids == new.candidate_ids and old.match_rule == new.match_rule
    assert atlas.equals(original_a) and sage.equals(original_s)
    stages = {r["stage"] for r in after.attrs["matching_attempts"]}
    assert {"MATCH_BAP", "MATCH_INDIVIDUAL"} <= stages


def test_excluded_types_are_not_residual_candidates(monkeypatch):
    """Une exclusion Sage empêche BAP et individuel sans fabriquer d'autres candidats."""
    atlas, sage = frames()
    monkeypatch.setattr(config, "SAGE_EXCLUDED_PREFIXES", ["CIF", "FAC"])
    result = match_reconciliations(atlas, sage)
    assert not result.match_rule.isin(["MATCH_BAP", "MATCH_INDIVIDUAL"]).any()


def test_missing_bap_is_manual_and_never_matches_another_project(tmp_path):
    """Un BAP absent produit au plus une proposition individuelle manuelle, jamais un autre projet."""
    from matching_helpers import atlas_row, sage_row, frames as prepare
    from reconciliation.exporters.review import export_review_bundle
    from reconciliation.multiples import build_controls
    a, s = prepare([atlas_row(**{"Année": 2026, "N° BAP (SAGE)": None})],
                  [sage_row(**{"Journal": "ACH", "N° de ligne comptable": "1", "N° de ligne Analytique": "1"})])
    result = match_reconciliations(a, s)
    assert result.iloc[0].match_rule == "MATCH_INDIVIDUAL"
    path = export_review_bundle(a, s, result, tmp_path / "missing.jsonl", controls=build_controls(a, s, result), include_sage_inventory=True)
    proposal = next(r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r.get("type") == "proposal")
    assert "auto_validation" not in proposal
    a, s = prepare([atlas_row(**{"Année": 2026})], [sage_row(Projet="OTHER")])
    assert match_reconciliations(a, s).iloc[0].match_status == "UNMATCHED"


def test_existing_candidate_group_is_not_reused():
    """Deux écritures d'un ancien match Montant restent indisponibles au recours individuel."""
    from matching_helpers import atlas_row, sage_row, frames as prepare
    a, s = prepare([atlas_row(Id="kept", **{"Année": 2026}),
                    atlas_row(Id="residual", **{"Année": 2026, "Libellé ATLAS": "Autre", "Total charges projet (€)": 600})],
                  [sage_row(**{"Charges (Dépenses)": amount}) for amount in (600, 400)])
    result = match_reconciliations(a, s)
    preserved = next(row for row in result.itertuples() if "kept" in row.atlas_source_ids)
    residual = next(row for row in result.itertuples() if "residual" in row.atlas_source_ids)
    assert preserved.match_rule == "MATCH_AMOUNT"
    assert residual.match_status == "UNMATCHED"


def test_repeated_unbalanced_amounts_do_not_repeat_all_proofs():
    """Deux cents Atlas concurrents partagent une proposition, pas une matrice de preuves."""
    from matching_helpers import atlas_row, sage_row, frames as prepare
    a, s = prepare([atlas_row(Id=str(i), **{"Année": 2026, "Libellé ATLAS": f"Atlas {i}", "Total charges projet (€)": 100}) for i in range(200)],
                  [sage_row(**{"Charges (Dépenses)": 100, "Libellé pièce": "Sage", "N° de ligne comptable": str(i),
                               "Journal": "ACH", "N° de ligne Analytique": "1"}) for i in range(300)])
    result = match_reconciliations(a, s)
    assert len(result) == 1
    assert result.iloc[0].atlas_row_count == 200 and result.iloc[0].sage_row_count == 300
    assert result.iloc[0].reason == "INDIVIDUAL_EVIDENCE_REVIEW"
