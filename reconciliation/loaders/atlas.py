"""Chargement multi-feuilles du JDD Atlas."""

import logging
from pathlib import Path

import pandas as pd

from reconciliation import config
from reconciliation.loaders.common import (
    LoaderError, record_summary, type_columns, validate_columns, validate_path,
)

logger = logging.getLogger(__name__)


class AtlasLoaderError(LoaderError):
    """Erreur de lecture, de structure ou de typage Atlas."""


def validate_atlas_columns(columns: pd.Index) -> None:
    """Vérifie le schéma minimal Atlas."""
    try:
        validate_columns(columns, config.ATLAS_REQUIRED_COLUMNS)
    except LoaderError as exc:
        raise AtlasLoaderError(str(exc)) from exc


def load_atlas(path: str | Path, *, year: int | None = None) -> pd.DataFrame:
    """Empile les feuilles valides puis conserve le premier exemplaire de chaque Id."""
    try:
        source = validate_path(path, ".xlsx")
        frames = []
        source_rows = 0
        with pd.ExcelFile(source, engine="openpyxl") as workbook:
            for sheet in workbook.sheet_names:
                header = pd.read_excel(workbook, sheet_name=sheet, nrows=0)
                try:
                    validate_atlas_columns(header.columns)
                except AtlasLoaderError as exc:
                    logger.warning("Feuille Atlas '%s' ignorée : %s", sheet, exc)
                    continue
                logger.info("Lecture de la feuille Atlas '%s'", sheet)
                frame = pd.read_excel(
                    workbook, sheet_name=sheet, dtype="string", keep_default_na=False,
                    na_values=[""],
                ).dropna(how="all")
                source_rows += len(frame)
                if year is not None:
                    if "Année" not in frame:
                        raise AtlasLoaderError(f"Feuille '{sheet}' : colonne Année requise pour --year")
                    years = pd.to_numeric(frame["Année"].str.replace(r"[ \u00a0\u202f]", "", regex=True), errors="coerce")
                    invalid = int(years.isna().sum())
                    if invalid:
                        logger.warning("Atlas '%s' : %s années absentes/invalides exclues", sheet, invalid)
                    frame = frame.loc[years.eq(year)].copy()
                if not frame.empty:
                    frames.append(frame)
        if not frames:
            if year is not None:
                raise AtlasLoaderError(f"Aucune ligne Atlas pour l'année {year}")
            raise AtlasLoaderError(
                "Aucune feuille Atlas valide non vide ; colonnes obligatoires attendues : "
                + ", ".join(config.ATLAS_REQUIRED_COLUMNS)
            )
        valid_sheets = len(frames)
        result = pd.concat(frames, ignore_index=True)
        del frames
        if result["Id"].isna().any() or result["Id"].str.strip().eq("").any():
            raise AtlasLoaderError("La colonne 'Id' contient des identifiants vides.")
        type_columns(
            result, config.ATLAS_TEXT_COLUMNS, config.ATLAS_DATE_COLUMNS,
            config.ATLAS_NUMERIC_COLUMNS, config.ATLAS_INTEGER_COLUMNS,
        )
        rows_read = len(result)
        result = result.drop_duplicates(subset=["Id"], keep="first", ignore_index=True)
        record_summary(result, "Atlas", rows_read, valid_sheets)
        if year is not None:
            result.attrs["load_summary"].update(rows_read=source_rows,
                rows_excluded_by_year=source_rows - rows_read, fiscal_year=year)
            logger.info("Atlas : %s lignes hors année %s exclues", source_rows - rows_read, year)
        return result
    except AtlasLoaderError:
        raise
    except Exception as exc:
        raise AtlasLoaderError(f"Impossible de charger Atlas '{path}' : {exc}") from exc
