"""Normalisation des données Atlas déjà chargées et typées."""

import pandas as pd

from reconciliation.config import ATLAS_CANONICAL_COLUMNS
from reconciliation.transformations.common import build_canonical


def transform_atlas(df: pd.DataFrame) -> pd.DataFrame:
    """Conserve les sources Atlas et ajoute les colonnes canoniques."""
    return build_canonical(df, ATLAS_CANONICAL_COLUMNS, "ATLAS")
