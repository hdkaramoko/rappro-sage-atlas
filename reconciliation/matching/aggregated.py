"""Agrégats complets, montants non partiels et index des candidats Sage."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from math import isclose, isfinite

import pandas as pd

from reconciliation.config import MATCHING_FULL_KEY, MATCHING_BLOCK_KEY


def amounts_compatible(atlas_amount, sage_amount, tolerance: float) -> bool:
    """Tolérance absolue ; marge de 1e-9 pour les seuls résidus flottants."""
    if pd.isna(atlas_amount) or pd.isna(sage_amount):
        return False
    if not isfinite(atlas_amount) or not isfinite(sage_amount):
        return False
    difference = abs(atlas_amount - sage_amount)
    return difference <= tolerance or (tolerance > 0 and isclose(difference, tolerance, rel_tol=0, abs_tol=1e-9))


def aggregate(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Groupby ; un montant absent invalide la somme entière du groupe."""
    grouped = frame.groupby(list(MATCHING_FULL_KEY), sort=False, dropna=False, observed=True)
    result = grouped.agg(
        row_count=("source_position", "size"),
        amount=("matching_amount", "sum"),
        amount_count=("matching_amount", "count"),
        source_ids=("source_id", tuple),
        source_positions=("source_position", tuple),
        documents=("accounting_document", lambda s: tuple(s.dropna().unique())),
        dates=("accounting_date", lambda s: tuple(s.dropna().unique())),
        document_count=("accounting_document", "count"),
        date_count=("accounting_date", "count"),
    ).reset_index()
    result["amount"] = result.amount.where(result.amount_count == result.row_count)
    result["group_id"] = [f"{prefix}:{i}" for i in range(len(result))]
    return result


def valid_key(group: dict, fields: tuple) -> bool:
    return all(pd.notna(group[field]) and group[field] != "" for field in fields)


class CandidateIndex:
    """Index structuré puis recherche dichotomique sur le montant, sans matrice globale."""

    def __init__(self, sage_groups: pd.DataFrame):
        blocks = defaultdict(list)
        self.groups = {}
        for group in sage_groups.to_dict("records"):
            self.groups[group["group_id"]] = group
            if valid_key(group, MATCHING_BLOCK_KEY) and pd.notna(group["amount"]):
                blocks[tuple(group[k] for k in MATCHING_BLOCK_KEY)].append(group)
        self.blocks = {}
        for key, groups in blocks.items():
            groups.sort(key=lambda g: g["amount"])
            self.blocks[key] = ([g["amount"] for g in groups], groups)

    def candidates(self, atlas: dict, tolerance: float) -> list[dict]:
        if not valid_key(atlas, MATCHING_BLOCK_KEY) or pd.isna(atlas["amount"]):
            return []
        amounts, groups = self.blocks.get(tuple(atlas[k] for k in MATCHING_BLOCK_KEY), ([], []))
        margin = tolerance + (1e-9 if tolerance else 0)
        start = bisect_left(amounts, atlas["amount"] - margin)
        end = bisect_right(amounts, atlas["amount"] + margin)
        return [g for g in groups[start:end] if amounts_compatible(atlas["amount"], g["amount"], tolerance)]
