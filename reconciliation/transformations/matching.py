"""Projection métier typée sans changer le contrat canonique de l'étape 2."""

import pandas as pd

from reconciliation.config import MATCHING_SOURCE_COLUMNS
from reconciliation.transformations.common import TransformationError, normalize_text


def prepare_matching(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Réutilise le canonique et prépare les champs métier additionnels.

    Entrée : résultat de transform_atlas/transform_sage. Les positions identifient
    les lignes de l'extraction même lorsque l'index est dupliqué.
    """
    required = ["project_code", "label", "reference", "accounting_document", "accounting_date"]
    if df.columns.has_duplicates or not set(required).issubset(df.columns):
        raise TransformationError("Matching : appeler les transformations sur un schéma sans doublons")
    result = df[required].copy().reset_index(drop=True)
    result["source_position"] = range(len(df))
    result["source_id"] = df["Id"].to_numpy() if source == "ATLAS" and "Id" in df else result.source_position
    for target, origin in MATCHING_SOURCE_COLUMNS[source].items():
        values = df[origin].reset_index(drop=True) if origin in df else pd.Series(pd.NA, index=result.index)
        if target.endswith("amount"):
            result[target] = pd.to_numeric(values, errors="coerce").astype("Float64")
            result[target] = result[target].where(result[target].abs() < float("inf"))
        else:
            result[target] = normalize_text(values, uppercase=target != "source_status")
    if source == "SAGE":
        result["matching_reference"] = result["reference"]
    return result
