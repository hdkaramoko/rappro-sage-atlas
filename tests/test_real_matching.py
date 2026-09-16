"""Validation opt-in des décisions sur le sous-ensemble réel profilé localement.

Prérequis : examples.profile_inputs puis examples.analyze_matching_inputs.
RECONCILIATION_REAL_TESTS=1 uv run pytest tests/test_real_matching.py
Les fichiers métier ne sont jamais nécessaires à la suite habituelle.
"""

import os

import pytest


@pytest.mark.skipif(os.environ.get("RECONCILIATION_REAL_TESTS") != "1", reason="Intégration locale sur données métier, activation explicite")
def test_prefilter_preserves_real_business_decisions():
    from examples.benchmark_sage_scope import main
    stats = main()  # Compare toutes les colonnes métier à l'exécution Sage complète.
    assert stats["business_results_equal"]
    assert stats["provenance_equal"]
    assert stats["sage_rows_after"] < stats["sage_rows_before"]
