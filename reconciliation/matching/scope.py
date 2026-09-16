"""Préfiltrage Sage par blocs Atlas, avec conservation de la provenance globale."""

import pandas as pd

from reconciliation.config import MATCHING_BLOCK_KEY, MATCHING_FULL_KEY


def restrict_sage(sage: pd.DataFrame, pending: pd.DataFrame, *, enabled: bool = True):
    """Garde tous les montants/libellés des blocs demandés, sans filtrage annuel.

    Entrées préparées : source_position/source_id sont déjà ceux de l'extraction
    complète. La numérotation vectorisée des groupes conserve aussi les anciens
    identifiants Sage et le compteur global pour le journal.
    """
    sage = sage.copy()
    numbers = sage.groupby(list(MATCHING_FULL_KEY), sort=False, dropna=False, observed=True).ngroup()
    sage["_group_number"] = numbers
    total_groups = int(numbers.max()) + 1 if len(numbers) else 0
    if enabled:
        keys = list(MATCHING_BLOCK_KEY)
        allowed = pd.MultiIndex.from_frame(pending[keys].dropna().drop_duplicates())
        mask = pd.MultiIndex.from_frame(sage[keys]).isin(allowed)
        sage = sage.loc[mask].copy()
    return sage, total_groups
