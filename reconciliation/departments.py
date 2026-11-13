"""Référentiels organisationnels Atlas et inventaires exhaustifs des projets."""

from collections import Counter
from pathlib import Path
import re
import unicodedata

import pandas as pd
from openpyxl import Workbook, load_workbook

from reconciliation.loaders.common import LoaderError
from reconciliation.transformations.common import normalize_text


def label_key(value):
    """Normalise Unicode, casse et espaces d'un libellé sans recherche approximative."""
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def header_key(value):
    """Résout accents et espaces des en-têtes, sans confondre leader et associé."""
    return "".join(c for c in unicodedata.normalize("NFKD", label_key(value)) if c.isalnum())


def excel_rows(path, sheet, columns):
    """Lit les lignes Excel textuelles et leur numéro après contrôle des colonnes.

    Ignore les lignes totalement vides, refuse les formules dans les colonnes
    requises et les en-têtes ambigus ; les autres colonnes restent sans effet.
    Lève LoaderError avec contexte ; ferme le classeur même en cas d'échec.
    Les identifiants ne subissent aucune conversion numérique.
    """
    try:
        with Path(path).open("rb") as stream:
            workbook = load_workbook(stream, read_only=True, data_only=False)
            try:
                if sheet not in workbook.sheetnames:
                    raise LoaderError(f"{path} : feuille {sheet} absente")
                rows = workbook[sheet].iter_rows(values_only=True)
                raw_headers = next(rows, ())
                headers = [header_key(v) for v in raw_headers]
                indexes = []
                for column in columns:
                    if headers.count(header_key(column)) != 1:
                        raise LoaderError(f"{path} : colonne requise absente ou répétée : {column}")
                    indexes.append(headers.index(header_key(column)))
                for number, values in enumerate(rows, 2):
                    if all(v is None or str(v).strip() == "" for v in values):
                        continue
                    if any(isinstance(values[i], str) and values[i].startswith("=") for i in indexes if i < len(values)):
                        raise LoaderError(f"{path}, ligne {number} : formule interdite")
                    yield number, [values[i] if i < len(values) else None for i in indexes], dict(zip(raw_headers, values))
            finally:
                workbook.close()
    except LoaderError:
        raise
    except Exception as exc:
        raise LoaderError(f"Lecture du référentiel impossible : {path} : {exc}") from exc


def project_context(atlas, sage, projects_path, mapping_path):
    """Construit une seule association par projet JDD et un bilan ensembliste.

    Valide strictement les deux Excel avant publication : contradiction, valeur
    manquante ou transcodification inconnue lèvent LoaderError. Un projet JDD
    absent du référentiel reste explicite et non renseigné. Retourne (table,
    bilan) ; ne modifie pas les DataFrames ni les clés de rapprochement.
    """
    mappings, references = {}, {}
    duplicates, totals = 0, 0
    for number, (source, target), _ in excel_rows(mapping_path, "Feuil1", ["Département leader", "Département consolidé"]):
        source, target = str(source or "").strip(), str(target or "").strip()
        if not source or not target or max(len(source), len(target)) > 255:
            raise LoaderError(f"Transcodification ligne {number} : département absent ou trop long")
        key = label_key(source)
        if key in mappings and mappings[key] != target:
            raise LoaderError(f"Transcodification contradictoire : {source}")
        mappings[key] = target
    if not mappings:
        raise LoaderError("Table de transcodification vide")
    unknown = set()
    project_rows = list(excel_rows(projects_path, "Sheet1", ["Code projet", "Département leader"]))
    normalized = normalize_text(pd.Series([row[1][0] for row in project_rows], dtype="string"), uppercase=True)
    markers = {header_key(v) for v in ("total", "totaux", "total general", "nombre de projets")}
    financial_columns = {header_key(v) for v in ("Montant total (€)", "Part EF (€)", "CA (€)",
        "Dépense budgétée (€)", "Dépenses réalisées (€)", "Prix total dépenses budgétées")}
    for (number, (raw_code, department), values), code in zip(project_rows, normalized):
        code = "" if pd.isna(code) else str(code)
        department = str(department or "").strip()
        # Une synthèse doit avoir un code absent ou explicitement marqué total.
        # Ne jamais retirer les deux dernières lignes par leur seule position.
        populated = {header_key(k): v for k, v in values.items() if v is not None and str(v).strip()}
        numeric_total = not code and bool(populated) and all(
            key in financial_columns and re.fullmatch(r"[+-]?\d[\d\s,.]*", str(value).strip())
            for key, value in populated.items())
        if not department and (numeric_total or (not code or header_key(code) in markers) and any(
                header_key(v) in markers for v in values.values() if isinstance(v, str))):
            totals += 1
            continue
        if not isinstance(raw_code, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,99}", code) or not department or len(department) > 255:
            raise LoaderError(f"Projets Atlas ligne {number} : code projet ou département absent/invalide")
        if code in references:
            if label_key(references[code]) != label_key(department):
                raise LoaderError(f"Départements contradictoires pour le projet {code}")
            duplicates += 1
        else:
            references[code] = department
        if label_key(department) not in mappings:
            unknown.add(department)
    if unknown:
        raise LoaderError("Départements sans transcodification : " + "; ".join(sorted(unknown)))
    atlas_codes = set(atlas["project_code"].dropna())
    sage_codes = set(sage["project_code"].dropna())
    table = {code: {"source": references.get(code, ""),
                    "consolidated": mappings.get(label_key(references.get(code)), ""),
                    "in_reference": code in references} for code in sorted(atlas_codes)}
    summary = {"atlas_projects": len(atlas_codes), "sage_projects": len(sage_codes),
               "intersection": len(atlas_codes & sage_codes), "sage_absent": len(sage_codes - atlas_codes),
               "atlas_without_department": sorted(atlas_codes - references.keys()),
               "reference_duplicates": duplicates, "reference_totals": totals}
    return table, summary


def project_exports(atlas, sage, table, folder, stem):
    """Écrit deux inventaires XLSX dans un dossier de préparation fourni par l'appelant.

    Un code unique par ligne, tri stable ; Sage couvre toute l'extraction chargée,
    y compris les types exclus du cadrage. Aucun total financier ajouté, afin de
    ne pas inventer de règle de devise. Retourne les deux chemins. Les chaînes
    sont forcées en texte pour éviter les formules Excel ; OSError est propagée.
    """
    atlas_counts = Counter(atlas["project_code"].dropna())
    sage_counts = Counter(sage["project_code"].dropna())
    outputs = []
    specifications = [
        (f"projets_jdd_atlas_{stem}.xlsx",
         ["Code projet", "Département leader (source)", "Département consolidé", "Présent dans le référentiel", "Lignes JDD", "Diagnostic"],
         [(code, table[code]["source"], table[code]["consolidated"], "Oui" if table[code]["in_reference"] else "Non",
           atlas_counts[code], "" if table[code]["in_reference"] else "Projet absent du référentiel") for code in sorted(atlas_counts)]),
        (f"projets_sage_absents_jdd_{stem}.xlsx", ["Code projet", "Nombre d'écritures Sage"],
         [(code, sage_counts[code]) for code in sorted(sage_counts.keys() - atlas_counts.keys())])]
    for name, headers, rows in specifications:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Projets"
        for number, values in enumerate([headers, *rows], 1):
            sheet.append(values)
            for column in range(1, len(values) + 1):
                cell = sheet.cell(number, column)
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        path = Path(folder) / name
        workbook.save(path)
        workbook.close()
        outputs.append(path)
    return outputs
