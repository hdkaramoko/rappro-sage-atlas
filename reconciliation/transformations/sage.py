"""Normalisation des données Sage déjà chargées et typées."""

import pandas as pd

from reconciliation.config import SAGE_CANONICAL_COLUMNS
from reconciliation.transformations.common import build_canonical


def transform_sage(df: pd.DataFrame) -> pd.DataFrame:
    """Conserve les sources Sage et ajoute les colonnes canoniques."""
    return build_canonical(df, SAGE_CANONICAL_COLUMNS, "SAGE")
