"""Classeur de restitution en écriture séquentielle, sans modification des sources."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from reconciliation.exporters.schema import ATLAS_EXPORT_COLUMNS, ATLAS_EXPORT_ALIASES, RESULT_COLUMNS, TRACE_LABELS
from reconciliation.matching.trace import TRACE_COLUMNS, iter_attempts

MAX_DATA_ROWS = 1_048_575
COLORS = {"MATCHED": "E2F0D9", "AMBIGUOUS": "FFF2CC", "UNMATCHED": "FCE4D6",
          "HORS_PERIMETRE": "E7E6E6", "RETENU": "E2F0D9", "REJETE": "FCE4D6"}


class ExportError(ValueError):
    """Le classeur ne peut pas être produit sans perte ou écrasement des sources."""


def canonical_atlas(atlas: pd.DataFrame) -> pd.DataFrame:
    """Harmonise les intitulés, conserve les valeurs ; colonnes absentes laissées vides."""
    output = pd.DataFrame(index=range(len(atlas)))
    for name in ATLAS_EXPORT_COLUMNS:
        origins = [c for c in (name, *ATLAS_EXPORT_ALIASES.get(name, ())) if c in atlas]
        if len(origins) > 1:
            a, b = atlas[origins[0]], atlas[origins[1]]
            if (a.notna() & b.notna() & a.ne(b)).any():
                raise ExportError(f"Colonnes alias contradictoires : {name}")
        if origins:
            values = atlas[origins[0]].reset_index(drop=True)
            for alias in origins[1:]:
                values = values.combine_first(atlas[alias].reset_index(drop=True))
            output[name] = values
        else:
            output[name] = None
    return output


def result_rows(atlas: pd.DataFrame, result: pd.DataFrame):
    """Redéploie les groupes sur les positions originales, jamais sur Id ou index."""
    by_position = {}
    for record in result.to_dict("records"):
        for position in record["atlas_source_positions"]:
            if position in by_position or not 0 <= position < len(atlas):
                raise ExportError("Positions Atlas dupliquées ou hors extraction dans le résultat")
            by_position[position] = record
    for position, values in enumerate(canonical_atlas(atlas).itertuples(index=False, name=None)):
        record = by_position.get(position, {
            "match_status": "HORS_PERIMETRE", "requires_review": False,
            "reason": "Statut Atlas différent de Envoyé SAGE ou absent",
        })
        yield (*values, *(record.get(key) for key in RESULT_COLUMNS))


def excel_value(value):
    """Pas de formule issue d'une source ; aucune troncature silencieuse de texte."""
    if isinstance(value, (tuple, list, dict, set, frozenset)):
        value = json.dumps(sorted(value) if isinstance(value, (set, frozenset)) else value,
                           ensure_ascii=False, default=str)
    elif value is None or pd.isna(value):
        return None
    elif isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    elif hasattr(value, "item"):
        value = value.item()
    if isinstance(value, str) and len(value) > 32767:
        raise ExportError("Une cellule dépasse 32 767 caractères ; réduire le périmètre de l'extraction")
    return value


def write_sheet(workbook, title, headers, rows):
    """Découpe automatiquement les feuilles à la limite Excel, en conservant l'ordre."""
    sheet, count, part = None, 0, 0

    def start_sheet():
        nonlocal part
        part += 1
        ws = workbook.create_sheet(title if part == 1 else f"{title}_{part}")
        ws.freeze_panes = "A2"
        ws.sheet_view.showGridLines = False
        for i, name in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(i)].width = min(45, max(16, len(name) + 2))
        cells = []
        for name in headers:
            cell = WriteOnlyCell(ws, name)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="24476A")
            cells.append(cell)
        ws.append(cells)
        return ws

    sheet = start_sheet()
    for row in rows:
        if count == MAX_DATA_ROWS:
            sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{count + 1}"
            sheet, count = start_sheet(), 0
        cells = []
        for name, value in zip(headers, row):
            value = excel_value(value)
            cell = WriteOnlyCell(sheet, value)
            if isinstance(value, str):
                cell.data_type = "s"
            elif isinstance(value, datetime):
                cell.number_format = "dd/mm/yyyy"
            elif "€" in name:
                cell.number_format = '#,##0.00'
            elif name in ("Confiance", "Similarité du libellé"):
                cell.number_format = "0.0%"
            if name in ("Statut du rapprochement", "Issue") and value in COLORS:
                cell.fill = PatternFill("solid", fgColor=COLORS[value])
            if name == "Revue nécessaire" and value is True:
                cell.fill = PatternFill("solid", fgColor="FFF2CC")
            cells.append(cell)
        sheet.append(cells)
        count += 1
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{count + 1}"


def export_reconciliation(atlas: pd.DataFrame, result: pd.DataFrame, output_path,
                          *, source_paths: dict | None = None) -> Path:
    """Écrit Résultats, Tentatives et Synthèse ; remplace la sortie seulement en succès.

    L'appel au moteur doit utiliser collect_trace=True. Les totaux de groupe
    répétés ne doivent pas être additionnés dans la feuille Résultats.
    """
    target = Path(output_path).resolve()
    source_paths = source_paths or {}
    if target.suffix.lower() != ".xlsx":
        raise ExportError("Le fichier de sortie doit porter l'extension .xlsx")
    if any(target == Path(p).resolve() or (target.exists() and Path(p).exists() and os.path.samefile(target, p))
           for p in source_paths.values()):
        raise ExportError("La sortie Excel ne doit pas remplacer un fichier source")
    if not result.attrs.get("trace_collected"):
        raise ExportError("Relancer le moteur avec collect_trace=True pour exporter les tentatives")
    if result.attrs["population_summary"]["atlas_rows_total"] != len(atlas):
        raise ExportError("Le résultat ne correspond pas à la taille de l'extraction Atlas")
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook(write_only=True)
    temporary = None
    try:
        write_sheet(workbook, "Résultats", (*ATLAS_EXPORT_COLUMNS, *RESULT_COLUMNS.values()), result_rows(atlas, result))
        attempts = iter_attempts(result)
        write_sheet(workbook, "Tentatives", TRACE_LABELS,
                    (tuple(row.get(key) for key in TRACE_COLUMNS) for row in attempts))
        summary = [("Exécution", "Date UTC", datetime.now(timezone.utc).isoformat()),
                   ("Lecture", "Granularité Résultats", "Une ligne par ligne Atlas après déduplication loader"),
                   ("Lecture", "Montants de groupe", "Répétés sur les lignes Atlas du groupe : ne pas additionner"),
                   ("Lecture", "RETENU dans Tentatives", "Candidat provisoire ; consulter DECISION_FINALE"),
                   ("Lecture", "Hors périmètre", "Statut Atlas différent de Envoyé SAGE ou absent"),
                   ("Lecture", "Positions", "Base zéro dans les extractions après chargement et déduplication")]
        summary.extend(("Fichiers", key, str(Path(path).resolve())) for key, path in source_paths.items())
        summary.extend(("Population", key, value) for key, value in result.attrs["population_summary"].items())
        summary.extend(("Résultats / groupes", key, value) for key, value in result.attrs["matching_summary"].items())
        summary.extend(("Lignes Atlas", rule, int(group.atlas_row_count.sum()))
                       for rule, group in result.groupby("match_rule", sort=False))
        summary.append(("Lignes Atlas", "À revoir", int(result.loc[result.requires_review.astype(bool), "atlas_row_count"].sum())))
        summary.extend(("Paramètres", key, value) for key, value in result.attrs["matching_options"].items())
        summary.extend(("Journal", key, result.attrs.get(key)) for key in ("trace_mode", "trace_row_count", "matching_trace_path"))
        write_sheet(workbook, "Synthèse", ("Rubrique", "Indicateur", "Valeur"), summary)
        with NamedTemporaryFile(dir=target.parent, suffix=".xlsx", delete=False) as handle:
            temporary = Path(handle.name)
        workbook.save(temporary)
        os.replace(temporary, target)
        return target
    except (OSError, ValueError) as exc:
        raise ExportError(f"Export Excel interrompu : {exc}") from exc
    finally:
        workbook.close()
        if temporary is not None and temporary.exists():
            temporary.unlink()
