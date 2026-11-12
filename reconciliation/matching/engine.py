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
from reconciliation.matching.trace import Trace
from reconciliation.matching.scope import restrict_sage

logger = logging.getLogger(__name__)


def summarize_matching(result: pd.DataFrame) -> dict[str, int]:
    """Nombre de résultats par règle (groupes, sauf les preuves Atlas individuelles)."""
    counts = result["match_rule"].value_counts()
    return {rule: int(counts.get(rule, 0)) for rule in RULES}


def match_reconciliations(atlas_df: pd.DataFrame, sage_df: pd.DataFrame,
                         options: MatchingConfig | None = None, *, collect_trace: bool = False,
                         trace_path=None, trace_mode: str = "compact") -> pd.DataFrame:
    """Rapproche sans mutation ; trace_path active un journal JSONL progressif.

    Sans chemin, collect_trace conserve un journal en mémoire pour petits jeux.
    Le mode compact regroupe les étapes ignorées et les rejets non fuzzy.
    """
    with Trace(collect_trace or trace_path is not None, path=trace_path, mode=trace_mode) as trace:
        return _match_reconciliations(atlas_df, sage_df, options, trace)


def _match_reconciliations(atlas_df, sage_df, options, trace):
    """Rapproche des DataFrames transformées et retourne un tableau indépendant.

    Les règles expérimentales proposent un match avec revue. Une preuve Sage
    incomplète interdit un statut cible automatique. Les entrées restent intactes.
    Les recours BAP puis individuel ne traitent que les UNMATCHED après toute
    la cascade ; leurs preuves individuelles enrichissent le catalogue existant.
    """
    options = options or MatchingConfig()
    atlas = prepare_matching(atlas_df, "ATLAS")
    selected = atlas.source_status.eq(ATLAS_STATUS_SENT_TO_SAGE).fillna(False)
    atlas = atlas.loc[selected]
    logger.info("%s lignes Atlas au statut %s", len(atlas), ATLAS_STATUS_SENT_TO_SAGE)
    confirmed = confirmed_atlas_mask(atlas)
    results = [confirmed_result(row) for row in atlas.loc[confirmed].to_dict("records")]
    for result in results:
        trace.add(result, "PREUVE_ATLAS", "RETENU", "Pièce, date et montant Sage présents dans Atlas")
        trace.skipped(result, {"PREUVE_ATLAS"}, "Preuve Atlas suffisante")
    logger.info("%s lignes validées directement depuis Atlas", len(results))
    pending = atlas.loc[~confirmed]
    sage_groups = pd.DataFrame()
    sage_rows_retained, sage_groups_total = 0, 0
    extra_candidates = []
    if not pending.empty:
        scoped_sage, sage_groups_total = restrict_sage(
            prepare_matching(sage_df, "SAGE"), pending, enabled=options.prefilter_sage,
        )
        sage_rows_retained = len(scoped_sage)
        logger.info("Périmètre Sage : %s lignes conservées sur %s", sage_rows_retained, len(sage_df))
        sage_groups = aggregate(scoped_sage, "SAGE")
        index = CandidateIndex(sage_groups)
        for group in aggregate(pending, "ATLAS").to_dict("records"):
            result = base_result(group)
            executed = {"PREUVE_ATLAS"}
            trace.add(result, "PREUVE_ATLAS", "REJETE", "Preuve Atlas absente ou incomplète", atlas=group)
            if not valid_key(group, MATCHING_BLOCK_KEY):
                result.reason = "INCOMPLETE_STRUCTURED_KEY"
            elif pd.isna(group["amount"]):
                result.reason = "INCOMPLETE_AMOUNT"
            else:
                candidates = index.candidates(group, options.amount_tolerance)
                block_count = index.block_counts.get(tuple(group[k] for k in MATCHING_BLOCK_KEY), 0)
                trace.add(result, "FILTRE_STRUCTURE", "EXECUTE", "Même projet, tiers et BAP / référence",
                          before=sage_groups_total, after=block_count, atlas=group)
                trace.add(result, "FILTRE_MONTANT", "EXECUTE", "Montant complet et compatible avec la tolérance",
                          before=block_count, after=len(candidates), atlas=group)
                executed.update(("FILTRE_STRUCTURE", "FILTRE_MONTANT", "MATCH_EXACT"))
                rule, chosen = exact_candidates(group, candidates)
                trace.candidates(result, "MATCH_EXACT", group, candidates, chosen if rule == "MATCH_EXACT" else [])
                if rule != "MATCH_EXACT":
                    executed.add("MATCH_AMOUNT")
                    trace.candidates(result, "MATCH_AMOUNT", group, candidates, chosen)
                scores = ()
                if rule is None and options.enable_fuzzy:
                    executed.add("FUZZY")
                    audit_scores = {} if trace.enabled else None
                    rule, chosen, scores = fuzzy_candidates(group, candidates, options, audit_scores=audit_scores)
                    trace.candidates(result, "FUZZY", group, candidates, chosen, audit_scores)
                if rule is None and options.enable_without_label and candidates:
                    executed.add("MATCH_WITHOUT_LABEL")
                    rule, chosen = MATCH_WITHOUT_LABEL, candidates
                    trace.candidates(result, "MATCH_WITHOUT_LABEL", group, candidates, chosen)
                if rule is not None:
                    apply_candidates(result, rule, chosen, scores, options)
            for stage, enabled in (("FUZZY", options.enable_fuzzy), ("MATCH_WITHOUT_LABEL", options.enable_without_label)):
                if not enabled and stage not in executed:
                    trace.add(result, stage, "NON_EXECUTE", "Étape désactivée dans la configuration")
                    executed.add(stage)
            if options.enable_residual and result.match_status == "UNMATCHED":
                executed.update(("MATCH_BAP", "MATCH_INDIVIDUAL"))  # Journalisés par les recours différés.
            trace.skipped(result, executed, "Prérequis absent ou cascade déjà arrêtée")
            results.append(result)
        resolve_shared_candidates(results)
        if options.enable_residual:
            from reconciliation.matching.residual import final_matches
            results, extra_candidates = final_matches(atlas_df, sage_df, results,
                {group["group_id"]: group for group in sage_groups.to_dict("records")}, options, trace)
            resolve_shared_candidates(results)
    for result in results:
        trace.add(result, "DECISION_FINALE", result.match_status, result.reason,
                  before=result.candidate_count, after=result.candidate_count)
    output = pd.DataFrame([asdict(result) for result in results], columns=[f.name for f in fields(MatchResult)])
    output.attrs["matching_summary"] = summarize_matching(output)
    output.attrs["population_summary"] = {
        "atlas_rows_total": len(atlas_df), "atlas_rows_selected": len(atlas),
        "atlas_rows_excluded": len(atlas_df) - len(atlas),
        "atlas_rows_confirmed": int(confirmed.sum()), "sage_groups": len(sage_groups),
        "sage_rows_total": len(sage_df), "sage_rows_retained": sage_rows_retained,
        "sage_groups_total": sage_groups_total,
        "sage_prefilter_applied": bool(options.prefilter_sage and not pending.empty),
        "sage_rows_excluded_by_prefilter": len(sage_df) - sage_rows_retained if options.prefilter_sage and not pending.empty else 0,
    }
    # Catalogue pour retrouver les lignes et preuves de chaque candidat ambigu.
    output.attrs["sage_candidates"] = sage_groups.to_dict("records") + extra_candidates
    output.attrs["matching_options"] = asdict(options)
    output.attrs["trace_collected"] = trace.enabled
    output.attrs["matching_attempts"] = trace.rows
    output.attrs["matching_trace_path"] = str(trace.path) if trace.path else None
    output.attrs["trace_mode"] = trace.mode
    output.attrs["trace_row_count"] = trace.count
    output.attrs["trace_id"] = trace.trace_id
    for rule, count in output.attrs["matching_summary"].items():
        logger.info("%s résultats %s", count, rule)
    return output
