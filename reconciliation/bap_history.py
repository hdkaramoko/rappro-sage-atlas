"""Lecture unique et jointure prudente de l'extraction informative des BAP Atlas."""

from collections import defaultdict
from datetime import date, datetime
from numbers import Real
import re

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from reconciliation.departments import header_key
from reconciliation.loaders.common import LoaderError
from reconciliation_contract.bap_history import bap_key, validate_record

COLUMNS = ("N° BAP SAGE", "Date de création", "Etabli par", "Date de modification", "Modifié par")


def excel_datetime(value, epoch):
    """Convertit date, datetime ou sériel Excel en ISO, sans inventer de fuseau.

    Accepte aussi ISO et dates françaises explicites. Retourne (valeur, invalide),
    avec None pour une absence ou une cellule invalide ; ne lève pas sur cellule.
    L'époque 1900/1904 du classeur et la fraction horaire sont respectées.
    """
    if value is None or isinstance(value, str) and not value.strip():
        return None, False
    try:
        if isinstance(value, bool):
            raise ValueError()
        if isinstance(value, Real):
            value = from_excel(value, epoch=epoch)
        elif isinstance(value, str):
            value = value.strip()
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                parsed = None
                for pattern in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
                    try:
                        parsed = datetime.strptime(value, pattern)
                        break
                    except ValueError:
                        pass
                if parsed is None:
                    raise ValueError()
                value = parsed
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time())
        if not isinstance(value, datetime):
            raise ValueError()
        return value.isoformat(), False
    except (ValueError, TypeError, OverflowError):
        return None, True


def history_context(path, atlas):
    """Lit une extraction XLSX et retourne (contextes joints, bilan anonymisé).

    Cinq colonnes requises, projet facultatif, une seule ouverture du classeur.
    Index par BAP/projet ; doublons cohérents acceptés, clés contradictoires
    neutralisées. Un projet discordant ou une référence ambiguë n'enrichit pas.
    Les pieds de tableau sont détectés par contenu. LoaderError signale les
    erreurs de fichier/schéma ; dates invalides et clés invalides sont comptées.
    Ne modifie ni Atlas ni aucune règle de rapprochement.
    """
    summary = {key: 0 for key in ("rows_read", "useful_rows", "total_rows", "empty_rows", "invalid_keys",
        "invalid_dates", "invalid_authors", "duplicates", "conflicts", "project_mismatches", "ambiguous_targets")}
    index, conflicted = {}, set()
    try:
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            if "Sheet1" not in workbook.sheetnames:
                raise LoaderError("Extraction BAP : feuille Sheet1 absente")
            rows = workbook["Sheet1"].iter_rows(values_only=True)
            raw_headers = next(rows, ())
            headers = [header_key(v) for v in raw_headers]
            positions = []
            for column in COLUMNS:
                if headers.count(header_key(column)) != 1:
                    raise LoaderError(f"Extraction BAP : colonne requise absente ou répétée : {column}")
                positions.append(headers.index(header_key(column)))
            if headers.count(header_key("Code projet")) > 1:
                raise LoaderError("Extraction BAP : Code projet répété")
            project_position = headers.index(header_key("Code projet")) if header_key("Code projet") in headers else None
            money_columns = {header_key("Total dépenses (€)"), header_key("Total dépenses (dev.)")}
            for values in rows:
                summary["rows_read"] += 1
                populated = {key: v for key, v in zip(headers, values) if v is not None and str(v).strip()}
                if not populated:
                    summary["empty_rows"] += 1
                    continue
                raw_bap, created, author, modified, modifier = [values[p] if p < len(values) else None for p in positions]
                bap = bap_key(raw_bap)
                project = values[project_position] if project_position is not None and project_position < len(values) else None
                if not bap and not project and (bool(values) and header_key(values[0]) == "total" or
                    all(key in money_columns and re.fullmatch(r"[+-]?\d[\d\s,.]*", str(v).strip()) for key, v in populated.items())):
                    summary["total_rows"] += 1
                    continue
                if not bap or project is not None and not isinstance(project, str):
                    summary["invalid_keys"] += 1
                    continue
                project = str(project or "").replace("\u00a0", " ").replace("\u202f", " ").strip().upper()
                if len(project) > 100:
                    summary["invalid_keys"] += 1
                    continue
                data = {}
                for field, value in (("bap_created_at", created), ("bap_modified_at", modified)):
                    data[field], invalid = excel_datetime(value, workbook.epoch)
                    summary["invalid_dates"] += invalid
                for field, value in (("bap_created_by", author), ("bap_modified_by", modifier)):
                    if value is None or isinstance(value, str) and not value.strip():
                        data[field] = None
                    elif isinstance(value, str) and len(value) <= 255 and not value.startswith("="):
                        data[field] = value
                    else:
                        data[field] = None
                        summary["invalid_authors"] += 1
                key = (bap, project)
                summary["useful_rows"] += 1
                if key in index:
                    if index[key] != data:
                        conflicted.add(key)
                    else:
                        summary["duplicates"] += 1
                else:
                    index[key] = data
        finally:
            workbook.close()
    except LoaderError:
        raise
    except Exception as exc:
        raise LoaderError("Extraction BAP illisible : vérifier le fichier XLSX et sa structure") from exc
    by_bap = defaultdict(dict)
    for (bap, project), data in index.items():
        by_bap[bap][project] = None if (bap, project) in conflicted else data
    targets = set()
    if "N° BAP (SAGE)" in atlas:
        for project, raw_bap in zip(atlas["project_code"], atlas["N° BAP (SAGE)"], strict=True):
            if isinstance(project, str) and (bap := bap_key(raw_bap)):
                targets.add((bap, project))
    records = []
    for bap, project in sorted(targets):
        candidates = by_bap.get(bap, {})
        if project not in candidates and "" in candidates and len(candidates) > 1:
            summary["ambiguous_targets"] += 1
            continue
        matching = [candidates[p] for p in (project, "") if p in candidates]
        if not matching:
            summary["project_mismatches"] += bool(candidates)
            continue
        if any(value is None for value in matching) or any(value != matching[0] for value in matching[1:]):
            summary["ambiguous_targets"] += 1
            continue
        records.append(validate_record({"project_code": project, "bap_sage_number": bap, **matching[0]}))
    summary.update(conflicts=len(conflicted), unique_baps=len(by_bap),
        baps_enriched=len({r["bap_sage_number"] for r in records}), contexts_enriched=len(records),
        extract_baps_not_in_jdd=len(set(by_bap)-{b for b, _ in targets}),
        jdd_baps_without_history=len(targets)-len(records))
    return records, summary
