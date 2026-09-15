"""Ambiguïtés de pièces/dates et concurrence entre groupes Atlas."""

from collections import defaultdict

from reconciliation.matching.models import AMBIGUOUS, MatchResult


def mark_ambiguous(result: MatchResult, reason: str) -> None:
    result.match_status = result.match_rule = AMBIGUOUS
    result.confidence = None
    result.requires_review = True
    result.target_status = None
    result.reason = reason


def incompatible_evidence(group: dict) -> bool:
    return len(group["documents"]) > 1 or len(group["dates"]) > 1


def resolve_shared_candidates(results: list[MatchResult]) -> None:
    """Chaque groupe revendiquant le même candidat devient ambigu, sans priorité d'ordre."""
    owners = defaultdict(list)
    for result in results:
        for candidate in result.candidate_ids:
            owners[candidate].append(result)
    for shared in owners.values():
        if len(shared) > 1:
            for result in shared:
                mark_ambiguous(result, "SAGE_CANDIDATE_SHARED")
