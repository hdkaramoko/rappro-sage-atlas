"""Similarité RapidFuzz uniquement sur des candidats structurés et filtrés."""

import pandas as pd
from rapidfuzz import fuzz

from reconciliation.matching.models import MATCH_FUZZY_HIGH, MATCH_FUZZY_REVIEW, MatchingConfig


def compute_label_similarity(atlas_label: str | None, sage_label: str | None,
                             method: str = "token_set_ratio") -> float:
    """Score [0, 1], zéro si libellé absent ; aucun nettoyage supplémentaire."""
    if method not in ("ratio", "token_set_ratio"):
        raise ValueError("Méthode fuzzy inconnue")
    if pd.isna(atlas_label) or pd.isna(sage_label) or not atlas_label or not sage_label:
        return 0.0
    scorer = fuzz.token_set_ratio if method == "token_set_ratio" else fuzz.ratio
    return scorer(atlas_label, sage_label) / 100.0


def fuzzy_candidates(atlas: dict, candidates: list[dict], options: MatchingConfig, *, audit_scores=None):
    """Conserve tous les candidats plausibles, sans choisir le meilleur arbitrairement."""
    scored = [(g, compute_label_similarity(atlas["label"], g["label"], options.fuzzy_method))
              for g in candidates if pd.notna(atlas["label"]) and pd.notna(g["label"])
              and atlas["label"] != "" and g["label"] != ""]
    plausible = [(g, score) for g, score in scored if score >= options.fuzzy_review_threshold]
    if audit_scores is not None:
        audit_scores.update((g["group_id"], score) for g, score in scored)
    if not plausible:
        return None, [], ()
    rule = MATCH_FUZZY_HIGH if max(score for _, score in plausible) >= options.fuzzy_high_threshold else MATCH_FUZZY_REVIEW
    return rule, [g for g, _ in plausible], tuple((g["group_id"], score) for g, score in plausible)
