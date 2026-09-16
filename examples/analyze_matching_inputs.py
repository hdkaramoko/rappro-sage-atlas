"""Analyse du sous-ensemble Atlas extrait par profile_inputs contre tout Sage.

Rapports locaux dans data/analysis, sans détails métier dans les logs.
Les positions Atlas de cette exécution sont locales au sous-ensemble.
"""

from collections import Counter
import json
from pathlib import Path
import time

import pandas as pd

from reconciliation import config
from reconciliation.loaders.common import type_columns
from reconciliation.loaders.sage import load_sage
from reconciliation.matching import match_reconciliations, MatchingConfig
from reconciliation.matching.aggregated import aggregate
from reconciliation.matching.trace import iter_attempts
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage
from reconciliation.transformations.matching import prepare_matching


def main():
    output = Path("data/analysis")
    a = pd.read_csv(output / "atlas_pending.csv", dtype="string", keep_default_na=False, na_values=[""])
    type_columns(a, config.ATLAS_TEXT_COLUMNS, config.ATLAS_DATE_COLUMNS,
                 config.ATLAS_NUMERIC_COLUMNS, config.ATLAS_INTEGER_COLUMNS)
    atlas = transform_atlas(a)
    sage = transform_sage(load_sage("data/inputs/ZLISTPJT.csv"))
    stats = {"pending_rows": len(a), "atlas_typing_issues": a.attrs["typing_issues"],
             "pending_years": {str(k): int(v) for k, v in a["Année"].value_counts().items()}}
    for source, frame in (("atlas", atlas), ("sage", sage)):
        start = time.perf_counter()
        prepared = prepare_matching(frame, source.upper())
        groups = aggregate(prepared, source.upper())
        block_sizes = groups.groupby(list(config.MATCHING_BLOCK_KEY), dropna=False).size()
        stats[source + "_groups"] = {
            "count": len(groups), "max_rows": int(groups.row_count.max()),
            "singleton_groups": int(groups.row_count.eq(1).sum()),
            "multi_document": int(groups.documents.map(len).gt(1).sum()),
            "multi_date": int(groups.dates.map(len).gt(1).sum()),
            "max_groups_per_block": int(block_sizes.max()),
            "p99_groups_per_block": float(block_sizes.quantile(.99)),
            "seconds": round(time.perf_counter()-start, 3),
        }
        if source == "atlas":
            atlas_keys = prepared[list(config.MATCHING_BLOCK_KEY)].dropna().drop_duplicates()
        else:
            stats["sage_rows_in_atlas_blocks"] = len(prepared.merge(atlas_keys, on=list(config.MATCHING_BLOCK_KEY), how="inner"))
        del groups, prepared
    start = time.perf_counter()
    result = match_reconciliations(atlas, sage, MatchingConfig(prefilter_sage=False), trace_path=output / "pending.tentatives.jsonl")
    stats["matching_seconds"] = round(time.perf_counter()-start, 3)
    stats["matching_summary"] = result.attrs["matching_summary"]
    stats["reasons"] = result.reason.value_counts().to_dict()
    stats["matching_rows"] = result.groupby("match_rule").atlas_row_count.sum().to_dict()
    stats["trace_rows"] = result.attrs["trace_row_count"]
    stats["trace_bytes"] = (output / "pending.tentatives.jsonl").stat().st_size
    stages, empty_blocks, empty_amount = Counter(), 0, 0
    max_candidates = 0
    for attempt in iter_attempts(result):
        stages[attempt["stage"]] += 1
        if attempt["stage"] == "FILTRE_STRUCTURE" and attempt["candidates_after"] == 0:
            empty_blocks += 1
        if attempt["stage"] == "FILTRE_MONTANT":
            max_candidates = max(max_candidates, attempt["candidates_after"])
            if attempt["candidates_before"] and not attempt["candidates_after"]:
                empty_amount += 1
    stats.update(trace_stages=dict(stages), empty_structured_blocks=empty_blocks,
                 blocks_without_compatible_amount=empty_amount, max_compatible_candidates=max_candidates)
    # Valeurs techniques uniquement : dates sentinelles et conventions numériques.
    raw = pd.read_csv("data/inputs/ZLISTPJT.csv", sep=";", encoding="utf-8-sig", dtype="string", keep_default_na=False,
                      usecols=["Date modification", "Date début de prestation", "Date fin de prestation", "Taux de TVA", "Tx devises de la pièce cptble"])
    stats["sage_technical_formats"] = {c: raw[c].value_counts().head(4).to_dict() for c in raw}
    result.to_pickle(output / "pending_results.pkl")
    (output / "matching_profile.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
