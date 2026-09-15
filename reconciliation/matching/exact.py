"""Preuve locale Atlas et règle sur la clé complète."""

import pandas as pd

from reconciliation.config import MATCHING_FULL_KEY
from reconciliation.matching.aggregated import valid_key
from reconciliation.matching.models import MATCH_EXACT, MATCH_AMOUNT


def confirmed_atlas_mask(atlas: pd.DataFrame) -> pd.Series:
    return atlas[["accounting_document", "accounting_date", "confirmed_amount"]].notna().all(axis=1)


def exact_candidates(atlas: dict, candidates: list[dict]) -> tuple[str | None, list[dict]]:
    """Les candidats fournis ont déjà un montant compatible."""
    if not valid_key(atlas, MATCHING_FULL_KEY):
        return None, []
    selected = [g for g in candidates if valid_key(g, MATCHING_FULL_KEY)
                and all(g[k] == atlas[k] for k in MATCHING_FULL_KEY)]
    if not selected:
        return None, []
    rule = MATCH_EXACT if selected[0]["row_count"] == atlas["row_count"] else MATCH_AMOUNT
    return rule, selected
