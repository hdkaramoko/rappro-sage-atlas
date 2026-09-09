"""Validations et conversions techniques communes aux sources."""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class LoaderError(ValueError):
    """Une source ne peut pas être chargée de manière fiable."""


def validate_path(path: str | Path, suffix: str) -> Path:
    """Contrôle l'existence et l'extension du fichier."""
    source = Path(path)
    if not source.is_file():
        raise LoaderError(f"Fichier inexistant ou non régulier : {source}")
    if source.suffix.lower() != suffix:
        raise LoaderError(f"Type de fichier incorrect : {source}. Attendu : {suffix}")
    return source


def validate_columns(columns: pd.Index, required: tuple[str, ...]) -> None:
    """Vérifie les colonnes obligatoires sans imposer les colonnes optionnelles."""
    missing = [name for name in required if name not in columns]
    if missing:
        raise LoaderError(f"Colonne(s) obligatoire(s) absente(s) : {', '.join(missing)}")
    if columns.has_duplicates:
        raise LoaderError("L'en-tête comporte des colonnes dupliquées.")


def type_columns(
    frame: pd.DataFrame,
    text: tuple[str, ...],
    dates: tuple[str, ...],
    numeric: tuple[str, ...],
    integers: tuple[str, ...],
    decimal: str = ",",
) -> None:
    """Applique les types sur place et compte les valeurs non convertibles."""
    issues = {}
    for column in text:
        if column in frame:
            frame[column] = frame[column].astype("string")
    for column in (*dates, *numeric, *integers):
        if column not in frame:
            continue
        values = frame[column].astype("string").str.strip().replace("", pd.NA)
        try:
            if column in dates:
                frame[column] = pd.to_datetime(
                    values, format="mixed", dayfirst=True, errors="coerce"
                ).astype("datetime64[ns]")
            else:
                values = values.str.replace(r"[ \u00a0\u202f]", "", regex=True)
                if decimal == ",":
                    values = values.str.replace(",", ".", regex=False)
                converted = pd.to_numeric(values, errors="coerce")
                converted = converted.mask(converted.isin([float("inf"), -float("inf")]))
                if column in integers:
                    converted = converted.mask(
                        (converted % 1 != 0)
                        | (converted < -(2 ** 63))
                        | (converted >= 2 ** 63)
                    )
                frame[column] = converted.astype(
                    "Int64" if column in integers else "Float64"
                )
        except (ValueError, TypeError, OverflowError) as exc:
            raise LoaderError(f"Erreur de typage dans la colonne '{column}'.") from exc
        invalid = int((values.notna() & frame[column].isna()).sum())
        if invalid:
            issues[column] = invalid
            logger.warning(
                "Colonne '%s' : %s valeurs non convertibles remplacées par des valeurs manquantes",
                column, invalid,
            )
    frame.attrs["typing_issues"] = issues


def record_summary(
    frame: pd.DataFrame, source: str, rows_read: int, valid_sheets: int | None = None
) -> None:
    """Expose les compteurs dans les logs et dans DataFrame.attrs."""
    removed = rows_read - len(frame)
    frame.attrs["load_summary"] = {
        "rows_read": rows_read, "duplicates_removed": removed,
        "rows_final": len(frame), "valid_sheets": valid_sheets,
    }
    if removed:
        logger.warning("%s : %s doublons supprimés", source, removed)
    logger.info("%s : %s lignes lues, %s lignes finales", source, rows_read, len(frame))
