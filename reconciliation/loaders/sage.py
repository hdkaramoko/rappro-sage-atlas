"""Lecture de l'extraction CSV annuelle Sage X3."""

import csv
import logging
import warnings
from pathlib import Path

import pandas as pd

from reconciliation import config
from reconciliation.loaders.common import (
    LoaderError, record_summary, type_columns, validate_columns, validate_path,
)

logger = logging.getLogger(__name__)


class SageLoaderError(LoaderError):
    """Erreur de lecture, de structure ou de typage Sage."""


def validate_sage_columns(columns: pd.Index) -> None:
    """Vérifie les colonnes essentielles de l'extraction Sage."""
    try:
        validate_columns(columns, config.SAGE_REQUIRED_COLUMNS)
    except LoaderError as exc:
        raise SageLoaderError(str(exc)) from exc


def _read_csv(path: Path, encoding: str, separator: str | None) -> pd.DataFrame:
    with path.open(encoding=encoding, newline="") as stream:
        header_line = stream.readline()
        if not header_line:
            raise SageLoaderError("Le CSV Sage est vide.")
        if separator is None:
            separator = csv.Sniffer().sniff(header_line, delimiters=";,").delimiter
        stream.seek(0)
        header = next(csv.reader(stream, delimiter=separator, strict=True))
        validate_sage_columns(pd.Index(header))
        stream.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", pd.errors.ParserWarning)
            return pd.read_csv(
                stream, sep=separator, dtype="string", keep_default_na=False,
                na_values=[""], on_bad_lines="error", index_col=False,
            )


def load_sage(
    path: str | Path,
    *,
    separator: str | None = config.SAGE_CSV_SEPARATOR,
    encoding: str = config.SAGE_CSV_ENCODING,
    decimal: str = config.SAGE_CSV_DECIMAL,
    year: int | None = None,
) -> pd.DataFrame:
    """Charge une année et supprime seulement les lignes sources identiques."""
    try:
        source = validate_path(path, ".csv")
        if separator not in (None, ";", ",") or decimal not in (".", ","):
            raise SageLoaderError("Séparateur ou caractère décimal non pris en charge.")
        try:
            result = _read_csv(source, encoding, separator)
        except UnicodeDecodeError:
            if encoding != config.SAGE_CSV_ENCODING:
                raise
            logger.warning("CSV Sage : relecture avec l'encodage Windows-1252")
            result = _read_csv(source, config.SAGE_CSV_FALLBACK_ENCODING, separator)
        rows_read = len(result)
        # Avant conversion : deux représentations distinctes ne sont pas des doublons stricts.
        result = result.drop_duplicates(keep="first", ignore_index=True)
        type_columns(
            result, config.SAGE_TEXT_COLUMNS, config.SAGE_DATE_COLUMNS,
            config.SAGE_NUMERIC_COLUMNS, config.SAGE_INTEGER_COLUMNS, decimal,
        )
        record_summary(result, "Sage", rows_read)
        if year is not None:
            summary = result.attrs["load_summary"].copy()
            before = len(result)
            invalid = int(result["Date comptable"].isna().sum())
            result = result.loc[result["Date comptable"].dt.year.eq(year)].copy().reset_index(drop=True)
            if result.empty:
                raise SageLoaderError(f"Aucune ligne SAGE avec une date comptable dans l'année {year}")
            summary.update(rows_final=len(result), rows_excluded_by_year=before - len(result),
                           invalid_accounting_dates=invalid, fiscal_year=year)
            result.attrs["load_summary"] = summary
            logger.info("SAGE : %s lignes exclues par l'année %s, dont %s dates absentes/invalides",
                        before - len(result), year, invalid)
        return result
    except SageLoaderError:
        raise
    except Exception as exc:
        raise SageLoaderError(f"Impossible de charger Sage '{path}' : {exc}") from exc
