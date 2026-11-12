"""Sécurité et comptage des instruments de profilage, sur petites bases fictives."""

import sqlite3
from unittest.mock import patch
import pytest

from benchmarks.profile_accounting import Meter, ROOT, configure_copy
from benchmarks.snapshot_accounting import snapshot


def test_exclusive_stages_do_not_double_count():
    """Deux étapes imbriquées totalisent dix secondes simulées, sans double comptage."""
    meter = Meter()
    with patch("benchmarks.profile_accounting.time.perf_counter", side_effect=[0, 2, 5, 10]):
        with meter.stage("outer"):
            with meter.stage("inner"):
                pass
    assert meter.stages == {"inner": 3, "outer": 7}


def test_backup_is_coherent_and_source_is_not_modified(tmp_path):
    """La copie seule accepte une écriture, la source conserve ses lignes et ne peut être écrasée."""
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (n INTEGER)")
        connection.execute("INSERT INTO sample VALUES (1)")
    result = snapshot(source, tmp_path / "isolated")
    with sqlite3.connect(result["copy"]) as connection:
        connection.execute("INSERT INTO sample VALUES (2)")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 1
    with pytest.raises(ValueError, match="existe"):
        snapshot(source, tmp_path / "isolated")


def test_working_database_cannot_be_used_as_benchmark_copy():
    """Le garde-fou refuse un chemin dans Git avant toute configuration Django ou écriture."""
    with pytest.raises(ValueError, match="hors du dépôt"):
        configure_copy(ROOT / "app-suivi-reconciliation/db.sqlite3")


def test_sql_parameters_are_not_retained():
    """Le rapport ne contient ni code projet ni paramètre financier utilisé par l'exécuteur."""
    meter = Meter()
    result = meter.execute(lambda sql, params, many, context: 42,
        "SELECT * FROM source WHERE project=%s", ["CONFIDENTIEL"], False, {})
    assert result == 42
    assert "CONFIDENTIEL" not in repr(meter.sql) + repr(meter.top)
