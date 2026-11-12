"""Le journal décrit les tentatives sans changer la décision de rapprochement."""

import pandas as pd

from matching_helpers import frames, atlas_row, sage_row
from reconciliation.matching import match_reconciliations, MatchingConfig


def test_trace_scores_rejections_and_final_decision():
    a, s = frames(sage=[sage_row(**{"Libellé pièce": "XYZ"})])
    plain = match_reconciliations(a, s)
    traced = match_reconciliations(a, s, collect_trace=True)
    pd.testing.assert_frame_equal(plain, traced)
    rows = traced.attrs["matching_attempts"]
    fuzzy = next(r for r in rows if r["stage"] == "FUZZY")
    assert fuzzy["outcome"] == "REJETE" and fuzzy["label_similarity"] == 0
    assert fuzzy["sage_documents"] == ("DOC-01",)
    assert rows[-1]["stage"] == "DECISION_FINALE" and rows[-1]["outcome"] == "MATCHED"
    assert plain.attrs["matching_attempts"] == []


def test_strict_skips_fuzzy_and_shared_candidate_final_is_ambiguous():
    a, s = frames([atlas_row(), atlas_row(Id="002", **{"Libellé ATLAS": "JANVIER DUPONT FACTURE CONSULTANT"})])
    rows = match_reconciliations(a, s, collect_trace=True, trace_mode="detailed").attrs["matching_attempts"]
    assert any(r["stage"] == "MATCH_EXACT" and r["outcome"] == "RETENU" for r in rows)
    assert any(r["stage"] == "FUZZY" and r["outcome"] == "NON_EXECUTE" for r in rows)
    final = [r for r in rows if r["stage"] == "DECISION_FINALE"]
    assert len(final) == 2 and all(r["outcome"] == "AMBIGUOUS" for r in final)


def test_filter_counts_include_missing_and_incompatible_amounts():
    a, s = frames(sage=[sage_row(), sage_row(**{"Libellé pièce": "X", "Charges (Dépenses)": None}),
                       sage_row(**{"Libellé pièce": "Y", "Charges (Dépenses)": 500}),
                       sage_row(Projet="AUTRE")])
    rows = match_reconciliations(a, s, collect_trace=True).attrs["matching_attempts"]
    structured = next(r for r in rows if r["stage"] == "FILTRE_STRUCTURE")
    amount = next(r for r in rows if r["stage"] == "FILTRE_MONTANT")
    assert (structured["candidates_before"], structured["candidates_after"]) == (4, 3)
    assert (amount["candidates_before"], amount["candidates_after"]) == (3, 1)


def test_confirmed_and_disabled_steps():
    a, s = frames([atlas_row(**{"N° pièce SAGE": "D", "Date comptable": pd.Timestamp("2026-01-01"), "Total charges SAGE (€)": 10})])
    rows = match_reconciliations(a, s, collect_trace=True).attrs["matching_attempts"]
    assert rows[0]["stage"] == "PREUVE_ATLAS" and rows[0]["outcome"] == "RETENU"
    assert all(r["outcome"] == "NON_EXECUTE" for r in rows[1:-1])
    a, s = frames(sage=[sage_row(**{"Libellé pièce": "XYZ"})])
    rows = match_reconciliations(a, s, MatchingConfig(enable_fuzzy=False), collect_trace=True).attrs["matching_attempts"]
    assert next(r for r in rows if r["stage"] == "FUZZY")["outcome"] == "NON_EXECUTE"


def test_disk_and_memory_have_same_attempts_and_decisions(tmp_path):
    from reconciliation.matching.trace import iter_attempts, json_value
    a, s = frames(sage=[sage_row(**{"Libellé pièce": "XYZ"})])
    memory = match_reconciliations(a, s, collect_trace=True)
    disk = match_reconciliations(a, s, trace_path=tmp_path / "audit.jsonl")
    pd.testing.assert_frame_equal(memory, disk)
    assert disk.attrs["matching_attempts"] == []
    assert list(iter_attempts(disk)) == json_value(memory.attrs["matching_attempts"])
    assert disk.attrs["trace_row_count"] == len(memory.attrs["matching_attempts"])


def test_compact_retains_all_fuzzy_scores_and_final_decisions():
    from reconciliation.matching.trace import iter_attempts
    a, s = frames(sage=[sage_row(**{"Libellé pièce": "XYZ"}), sage_row(**{"Libellé pièce": "ABC"})])
    compact = match_reconciliations(a, s, collect_trace=True)
    detailed = match_reconciliations(a, s, collect_trace=True, trace_mode="detailed")
    pd.testing.assert_frame_equal(compact, detailed)
    for stage in ("FUZZY", "DECISION_FINALE"):
        assert [r for r in iter_attempts(compact) if r["stage"] == stage] == [r for r in iter_attempts(detailed) if r["stage"] == stage]
    assert compact.attrs["trace_row_count"] < detailed.attrs["trace_row_count"]


def test_confirmed_compact_has_three_rows_instead_of_all_stages():
    """Le compact résume les étapes ignorées, y compris les nouveaux recours finaux."""
    a, s = frames([atlas_row(**{"N° pièce SAGE": "D", "Date comptable": pd.Timestamp("2026-01-01"), "Total charges SAGE (€)": 10})])
    compact = match_reconciliations(a, s, collect_trace=True)
    detailed = match_reconciliations(a, s, collect_trace=True, trace_mode="detailed")
    assert compact.attrs["trace_row_count"] == 3
    from reconciliation.matching.trace import STAGES
    assert detailed.attrs["trace_row_count"] == len(STAGES) + 1
    skipped = compact.attrs["matching_attempts"][1]
    assert skipped["stage"] == "ETAPES_NON_EXECUTEES" and "FUZZY" in skipped["reason"]


def test_incremental_write_without_retaining_rows(tmp_path):
    from reconciliation.matching.trace import Trace
    from reconciliation.matching.models import MatchResult
    result = MatchResult("A", ("001",), (0,), 1, 0.)
    with Trace(True, path=tmp_path / "trace.jsonl", flush_every=2) as trace:
        for _ in range(10000):
            trace.add(result, "PREUVE_ATLAS", "RETENU", "Test")
        assert trace.rows == []
        assert trace.temporary.stat().st_size > 0
        assert trace.count == 10000
    assert (tmp_path / "trace.jsonl").exists()
    assert not list(tmp_path.glob("*.part"))


def test_failed_run_preserves_previous_trace(tmp_path):
    import pytest
    from reconciliation.matching.trace import Trace
    path = tmp_path / "trace.jsonl"
    path.write_text("previous", encoding="utf-8")
    with pytest.raises(RuntimeError):
        with Trace(True, path=path):
            raise RuntimeError("Interrupted")
    assert path.read_text() == "previous"
    assert not list(tmp_path.glob("*.part"))


def test_truncated_trace_is_rejected(tmp_path):
    import pytest
    from reconciliation.matching.trace import iter_attempts, TraceError
    a, s = frames()
    path = tmp_path / "trace.jsonl"
    result = match_reconciliations(a, s, trace_path=path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(TraceError, match="marqueur"):
        list(iter_attempts(result))


def test_trace_replaced_by_another_run_is_detected(tmp_path):
    import pytest
    from reconciliation.matching.trace import iter_attempts, TraceError
    a, s = frames()
    path = tmp_path / "trace.jsonl"
    first = match_reconciliations(a, s, trace_path=path)
    second = match_reconciliations(a, s, trace_path=path)
    assert len(list(iter_attempts(second))) == second.attrs["trace_row_count"]
    with pytest.raises(TraceError, match="autre exécution"):
        list(iter_attempts(first))
