"""Validation du préfiltrage intégré contre la référence locale Sage complète."""

import json
from pathlib import Path
import time

import pandas as pd

from reconciliation import config
from reconciliation.loaders.common import type_columns
from reconciliation.loaders.sage import load_sage
from reconciliation.matching import match_reconciliations
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage


def main():
    directory = Path("data/analysis")
    # Pickle créé localement par analyze_matching_inputs ; jamais un fichier externe.
    baseline = pd.read_pickle(directory / "pending_results.pkl")
    raw = pd.read_csv(directory / "atlas_pending.csv", dtype="string", keep_default_na=False, na_values=[""])
    type_columns(raw, config.ATLAS_TEXT_COLUMNS, config.ATLAS_DATE_COLUMNS, config.ATLAS_NUMERIC_COLUMNS, config.ATLAS_INTEGER_COLUMNS)
    atlas, sage = transform_atlas(raw), transform_sage(load_sage("data/inputs/ZLISTPJT.csv"))
    start = time.perf_counter()
    result = match_reconciliations(atlas, sage, trace_path=directory / "filtered.tentatives.jsonl")
    matching_seconds = time.perf_counter() - start
    print(f"Matching avec préfiltrage intégré : {matching_seconds:.3f}s", flush=True)
    retained = result.attrs["population_summary"]["sage_rows_retained"]
    # pandas recopie attrs lors des projections : retirer les catalogues du banc
    # de comparaison pour ne pas les recopier à chaque colonne comparée.
    baseline.attrs.clear()
    result.attrs.clear()
    pd.testing.assert_frame_equal(baseline, result)
    rows = baseline[["atlas_source_positions", "match_rule"]].explode("atlas_source_positions")
    rows["year"] = rows.atlas_source_positions.map(raw["Année"].to_dict())
    yearly = pd.crosstab(rows.year, rows.match_rule)
    stats = {"sage_rows_before": len(sage), "sage_rows_after": retained,
             "matching_seconds": round(matching_seconds, 3), "provenance_equal": True,
             "business_results_equal": True, "yearly_outcomes": yearly.to_dict()}
    (directory / "scope_benchmark.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=True, indent=2), flush=True)
    return stats


if __name__ == "__main__":
    main()
