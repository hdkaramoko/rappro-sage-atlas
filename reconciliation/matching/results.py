"""Construction des résultats et enrichissements proposés, jamais appliqués aux sources."""

import pandas as pd

from reconciliation.config import ATLAS_STATUS_ACCOUNTED
from reconciliation.matching.ambiguous import incompatible_evidence, mark_ambiguous
from reconciliation.matching.models import (
    MATCHED, MATCH_EXACT, MATCH_CONFIRMED_ATLAS, MatchResult, MatchingConfig,
)
from reconciliation.matching.scoring import compute_confidence


def base_result(group: dict) -> MatchResult:
    return MatchResult(
        atlas_group_id=group["group_id"], atlas_source_ids=group["source_ids"],
        atlas_source_positions=group["source_positions"], atlas_row_count=group["row_count"],
        atlas_amount=None if pd.isna(group["amount"]) else float(group["amount"]),
    )


def confirmed_result(row: dict) -> MatchResult:
    """La preuve est locale à Atlas ; aucune ligne Sage n'est revendiquée."""
    result = MatchResult(
        atlas_group_id=f"ATLAS_CONFIRMED:{row['source_position']}",
        atlas_source_ids=(row["source_id"],), atlas_source_positions=(row["source_position"],),
        atlas_row_count=1,
        atlas_amount=None if pd.isna(row["matching_amount"]) else float(row["matching_amount"]),
        match_status=MATCHED, match_rule=MATCH_CONFIRMED_ATLAS,
        confidence=1.0, requires_review=False, target_status=ATLAS_STATUS_ACCOUNTED,
        sage_document_number=row["accounting_document"],
        sage_accounting_date=row["accounting_date"], sage_amount=float(row["confirmed_amount"]),
        sage_document_numbers=(row["accounting_document"],),
        sage_accounting_dates=(row["accounting_date"],), reason="ATLAS_EVIDENCE_PRESENT",
    )
    if result.atlas_amount is not None:
        result.amount_difference = result.atlas_amount - result.sage_amount
    return result


def apply_candidates(result: MatchResult, rule: str, candidates: list[dict],
                     scores: tuple, options: MatchingConfig) -> MatchResult:
    result.candidate_count = len(candidates)
    result.candidate_ids = tuple(g["group_id"] for g in candidates)
    result.candidate_scores = scores
    if len(candidates) != 1:
        mark_ambiguous(result, "MULTIPLE_CANDIDATES")
        return result
    group = candidates[0]
    result.sage_group_id = group["group_id"]
    result.sage_source_ids = group["source_ids"]
    result.sage_row_count = group["row_count"]
    result.sage_amount = float(group["amount"])
    result.amount_difference = result.atlas_amount - result.sage_amount
    result.cardinality_match = result.atlas_row_count == result.sage_row_count
    result.sage_document_numbers = group["documents"]
    result.sage_accounting_dates = group["dates"]
    result.label_similarity = scores[0][1] if scores else None
    if incompatible_evidence(group):
        mark_ambiguous(result, "INCOMPATIBLE_SAGE_EVIDENCE")
        return result
    result.sage_document_number = group["documents"][0] if group["documents"] else None
    result.sage_accounting_date = pd.Timestamp(group["dates"][0]) if group["dates"] else None
    result.match_status = MATCHED
    result.match_rule = rule
    result.confidence = compute_confidence(rule, result.label_similarity, options)
    complete = group["document_count"] == group["date_count"] == group["row_count"]
    result.requires_review = rule != MATCH_EXACT or not complete
    result.reason = "UNIQUE_CANDIDATE" if complete else "INCOMPLETE_SAGE_EVIDENCE"
    if complete and (rule == MATCH_EXACT or rule in options.auto_account_rules):
        result.target_status = ATLAS_STATUS_ACCOUNTED
    return result
