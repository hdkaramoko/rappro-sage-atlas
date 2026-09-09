"""Construction vectorisée du modèle canonique sans modifier les sources."""

import logging

import pandas as pd

logger = logging.getLogger(__name__)
IDENTIFIER_COLUMNS = {"project_code", "reference", "accounting_document", "currency"}


class TransformationError(ValueError):
    """Le modèle canonique ne peut pas être construit sans perte de données."""


def normalize_text(values: pd.Series, *, uppercase: bool = False) -> pd.Series:
    """Nettoie les bords et espaces insécables, sans retirer les séparateurs."""
    result = (
        values.astype("string")
        .str.replace("\u00a0", " ", regex=False)
        .str.replace("\u202f", " ", regex=False)
        .str.strip()
        .replace("", pd.NA)
    )
    return result.str.upper() if uppercase else result


def build_canonical(
    df: pd.DataFrame, mapping: dict[str, str | None], source: str
) -> pd.DataFrame:
    """Ajoute les champs canoniques ; conserve lignes, index et colonnes sources."""
    collisions = set(df.columns) & (set(mapping) | {"source"})
    if collisions or df.columns.has_duplicates:
        raise TransformationError(
            "Colonnes dupliquées ou noms canoniques déjà présents : "
            + ", ".join(sorted(collisions))
        )
    result = df.copy()
    for target, origin in mapping.items():
        dtype = (
            "Float64" if target == "amount"
            else "datetime64[ns]" if target == "accounting_date" else "string"
        )
        if origin is None or origin not in df:
            result[target] = pd.Series(index=df.index, dtype=dtype)
        elif target in ("amount", "accounting_date"):
            result[target] = df[origin].astype(dtype)
        else:
            result[target] = normalize_text(
                df[origin], uppercase=target in IDENTIFIER_COLUMNS
            )
    result["source"] = pd.Series(source, index=df.index, dtype="string")
    missing = int(result["project_code"].isna().sum())
    result.attrs["transformation_summary"] = {
        "rows_transformed": len(result), "missing_project_codes": missing,
    }
    logger.info("%s : %s lignes transformées, %s codes projet manquants", source, len(result), missing)
    return result
