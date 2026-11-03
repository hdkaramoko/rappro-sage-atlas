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
    """Charge `path` XLSX, filtre `year` puis conserve le premier exemplaire de chaque Id.

    Retourne un DataFrame typé, ses compteurs de doublons/conflits et deux
    colonnes décimales sources privées pour les charges EUR de l'inventaire.
    Ces colonnes évitent un passage par float dans les calculs comptables sans
    changer les colonnes historiques du matching. Lève AtlasLoaderError si
    fichier invalide, Id absent ou population annuelle vide. Lecture seule.
    """
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
        rows_read = len(result)
        repeated = result.loc[result.duplicated('Id', keep=False)]
        conflicting = repeated.drop_duplicates().groupby('Id').size().gt(1)
        conflicting_ids = int(conflicting.sum())
        if conflicting_ids:
            logger.warning("Atlas : %s Id contradictoires ; contrôles multiples indéterminés", conflicting_ids)
        from reconciliation_contract.atlas_context import ATLAS_CONTEXT, ATLAS_CONTEXT_ALIASES, context_number
        for column, aliases in ATLAS_CONTEXT_ALIASES.items():
            for alias in aliases:
                if alias in result:
                    if column in result:
                        raise AtlasLoaderError(f"Colonnes en double : {column} et {alias}")
                    result[column] = result[alias]
        for column in ATLAS_CONTEXT:
            if column in result:
                try:
                    result[column] = result[column].map(
                        lambda value: context_number(None if pd.isna(value) else value)
                    )
                except ValueError as exc:
                    raise AtlasLoaderError(f"Colonne {column} : {exc}") from exc
        from reconciliation_contract import money
        for column, target in (("Total charges SAGE (€)", "_total_sage_decimal"),
                               ("Total charges projet (€)", "_total_project_decimal")):
            if column in result:
                values = result[column].str.replace(r"[ \u00a0\u202f]", "", regex=True).str.replace(",", ".", regex=False)
                result[target] = values.map(lambda value: str(money(value)) if money(value) is not None else None)
        type_columns(
            result, config.ATLAS_TEXT_COLUMNS, config.ATLAS_DATE_COLUMNS,
            config.ATLAS_NUMERIC_COLUMNS, config.ATLAS_INTEGER_COLUMNS,
        )
        result = result.drop_duplicates(subset=["Id"], keep="first", ignore_index=True)
        record_summary(result, "Atlas", rows_read, valid_sheets)
        result.attrs['load_summary']['conflicting_ids'] = conflicting_ids
        result.attrs['load_summary']['technical_duplicates_removed'] = rows_read - len(result) - int((repeated.drop_duplicates().groupby('Id').size() - 1).clip(lower=0).sum())
        if year is not None:
            result.attrs["load_summary"].update(rows_read=source_rows,
                rows_excluded_by_year=source_rows - rows_read, fiscal_year=year)
            logger.info("Atlas : %s lignes hors année %s exclues", source_rows - rows_read, year)
        return result
    except AtlasLoaderError:
        raise
    except Exception as exc:
        raise AtlasLoaderError(f"Impossible de charger Atlas '{path}' : {exc}") from exc
