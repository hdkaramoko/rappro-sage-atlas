"""Contrat public des résultats et options du rapprochement."""

from dataclasses import dataclass
from math import isfinite

from reconciliation import config

MATCHED = "MATCHED"
MATCH_CONFIRMED_ATLAS = "MATCH_CONFIRMED_ATLAS"
MATCH_EXACT = "MATCH_EXACT"
MATCH_AMOUNT = "MATCH_AMOUNT"
MATCH_FUZZY_HIGH = "MATCH_FUZZY_HIGH"
MATCH_FUZZY_REVIEW = "MATCH_FUZZY_REVIEW"
MATCH_WITHOUT_LABEL = "MATCH_WITHOUT_LABEL"
AMBIGUOUS = "AMBIGUOUS"
UNMATCHED = "UNMATCHED"
RULES = (MATCH_CONFIRMED_ATLAS, MATCH_EXACT, MATCH_AMOUNT, MATCH_FUZZY_HIGH,
         MATCH_FUZZY_REVIEW, MATCH_WITHOUT_LABEL, AMBIGUOUS, UNMATCHED)
EXPERIMENTAL_RULES = frozenset((MATCH_AMOUNT, MATCH_FUZZY_HIGH, MATCH_FUZZY_REVIEW, MATCH_WITHOUT_LABEL))


@dataclass(frozen=True)
class MatchingConfig:
    """Options d'un appel ; validation expérimentale désactivée par défaut."""

    amount_tolerance: float = config.AMOUNT_TOLERANCE
    fuzzy_high_threshold: float = config.FUZZY_HIGH_THRESHOLD
    fuzzy_review_threshold: float = config.FUZZY_REVIEW_THRESHOLD
    amount_confidence: float = config.MATCH_AMOUNT_CONFIDENCE
    without_label_confidence: float = config.MATCH_WITHOUT_LABEL_CONFIDENCE
    fuzzy_method: str = "token_set_ratio"
    enable_fuzzy: bool = True
    enable_without_label: bool = True
    prefilter_sage: bool = True
    auto_account_rules: frozenset[str] = frozenset()

    def __post_init__(self):
        if not isfinite(self.amount_tolerance) or self.amount_tolerance < 0:
            raise ValueError("La tolérance doit être finie et positive ou nulle")
        for value in (self.fuzzy_high_threshold, self.fuzzy_review_threshold,
                      self.amount_confidence, self.without_label_confidence):
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Les seuils et confiances doivent être entre 0 et 1")
        if self.fuzzy_review_threshold > self.fuzzy_high_threshold:
            raise ValueError("Le seuil de revue doit être inférieur au seuil élevé")
        if self.fuzzy_method not in ("ratio", "token_set_ratio"):
            raise ValueError("Méthode fuzzy inconnue")
        if not set(self.auto_account_rules) <= EXPERIMENTAL_RULES:
            raise ValueError("Seules les règles expérimentales peuvent être autorisées explicitement")


@dataclass
class MatchResult:
    """Une preuve Atlas ou un groupe Atlas ; tuples pour les provenances."""

    atlas_group_id: str
    atlas_source_ids: tuple
    atlas_source_positions: tuple
    atlas_row_count: int
    atlas_amount: float | None
    source_status: str = config.ATLAS_STATUS_SENT_TO_SAGE
    match_status: str = UNMATCHED
    match_rule: str = UNMATCHED
    confidence: float | None = 0.0
    requires_review: bool = True
    label_similarity: float | None = None
    sage_row_count: int | None = None
    sage_amount: float | None = None
    amount_difference: float | None = None
    cardinality_match: bool | None = None
    sage_document_number: str | None = None
    sage_accounting_date: object = None
    sage_document_numbers: tuple = ()
    sage_accounting_dates: tuple = ()
    sage_source_ids: tuple = ()
    sage_group_id: str | None = None
    target_status: str | None = None
    candidate_count: int = 0
    candidate_ids: tuple = ()
    candidate_scores: tuple = ()
    reason: str = "NO_CANDIDATE"
