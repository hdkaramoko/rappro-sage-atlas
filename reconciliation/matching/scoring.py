"""Indicateurs métier explicables, sans interprétation probabiliste."""

from reconciliation.matching.models import (
    MATCH_CONFIRMED_ATLAS, MATCH_EXACT, MATCH_AMOUNT, MATCH_FUZZY_HIGH,
    MATCH_FUZZY_REVIEW, MATCH_WITHOUT_LABEL, AMBIGUOUS, MatchingConfig,
)


def compute_confidence(rule: str, similarity: float | None, options: MatchingConfig) -> float | None:
    if rule in (MATCH_CONFIRMED_ATLAS, MATCH_EXACT):
        return 1.0
    if rule == MATCH_AMOUNT:
        return options.amount_confidence
    if rule in (MATCH_FUZZY_HIGH, MATCH_FUZZY_REVIEW):
        return similarity
    if rule == MATCH_WITHOUT_LABEL:
        return options.without_label_confidence
    return None if rule == AMBIGUOUS else 0.0
