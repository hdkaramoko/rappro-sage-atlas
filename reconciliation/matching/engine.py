"""Cascade explicable : preuve Atlas, clé complète, fuzzy, sans libellé."""

from dataclasses import asdict, fields
import logging

import pandas as pd

from reconciliation.config import ATLAS_STATUS_SENT_TO_SAGE, MATCHING_BLOCK_KEY
from reconciliation.transformations.matching import prepare_matching
from reconciliation.matching.aggregated import CandidateIndex, aggregate, valid_key
from reconciliation.matching.ambiguous import resolve_shared_candidates
from reconciliation.matching.exact import confirmed_atlas_mask, exact_candidates
from reconciliation.matching.fuzzy import fuzzy_candidates
from reconciliation.matching.models import MATCH_WITHOUT_LABEL, RULES, MatchResult, MatchingConfig
from reconciliation.matching.results import base_result, confirmed_result, apply_candidates

logger = logging.getLogger(__name__)


def summarize_matching(result: pd.DataFrame) -> dict[str, int]:
    """Nombre de résultats par règle (groupes, sauf les preuves Atlas individuelles)."""
    counts = result["match_rule"].value_counts()
    return {rule: int(counts.get(rule, 0)) for rule in RULES}


def match_reconciliations(atlas_df: pd.DataFrame, sage_df: pd.DataFrame,
                         options: MatchingConfig | None = None) -> pd.DataFrame:
    """Rapproche des DataFrames transformées et retourne un tableau indépendant.

    Les règles expérimentales proposent un match avec revue. Une preuve Sage
    incomplète interdit un statut cible automatique. Les entrées restent intactes.
    """
    options = options or MatchingConfig()
    atlas = prepare_matching(atlas_df, "ATLAS")
    selected = atlas.source_status.eq(ATLAS_STATUS_SENT_TO_SAGE).fillna(False)
    atlas = atlas.loc[selected]
    logger.info("%s lignes Atlas au statut %s", len(atlas), ATLAS_STATUS_SENT_TO_SAGE)
    confirmed = confirmed_atlas_mask(atlas)
    results = [confirmed_result(row) for row in atlas.loc[confirmed].to_dict("records")]
    logger.info("%s lignes validées directement depuis Atlas", len(results))
    pending = atlas.loc[~confirmed]
    sage_groups = pd.DataFrame()
    if not pending.empty:
        sage_groups = aggregate(prepare_matching(sage_df, "SAGE"), "SAGE")
        index = CandidateIndex(sage_groups)
        for group in aggregate(pending, "ATLAS").to_dict("records"):
            result = base_result(group)
            if not valid_key(group, MATCHING_BLOCK_KEY):
                result.reason = "INCOMPLETE_STRUCTURED_KEY"
            elif pd.isna(group["amount"]):
                result.reason = "INCOMPLETE_AMOUNT"
            else:
                candidates = index.candidates(group, options.amount_tolerance)
                rule, chosen = exact_candidates(group, candidates)
                scores = ()
                if rule is None and options.enable_fuzzy:
                    rule, chosen, scores = fuzzy_candidates(group, candidates, options)
                if rule is None and options.enable_without_label and candidates:
                    rule, chosen = MATCH_WITHOUT_LABEL, candidates
                if rule is not None:
                    apply_candidates(result, rule, chosen, scores, options)
            results.append(result)
        resolve_shared_candidates(results)
    output = pd.DataFrame([asdict(result) for result in results], columns=[f.name for f in fields(MatchResult)])
    output.attrs["matching_summary"] = summarize_matching(output)
    output.attrs["population_summary"] = {
        "atlas_rows_total": len(atlas_df), "atlas_rows_selected": len(atlas),
        "atlas_rows_excluded": len(atlas_df) - len(atlas),
        "atlas_rows_confirmed": int(confirmed.sum()), "sage_groups": len(sage_groups),
    }
    # Catalogue pour retrouver les lignes et preuves de chaque candidat ambigu.
    output.attrs["sage_candidates"] = sage_groups.to_dict("records")
    for rule, count in output.attrs["matching_summary"].items():
        logger.info("%s résultats %s", count, rule)
    return output
