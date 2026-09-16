"""Profilage local exhaustif, sans charger le classeur Atlas entier en mémoire.

Lecture XML séquentielle du XLSX pour les statistiques (pas un loader métier).
Les détails restent dans data/analysis, ignoré par Git. Aucun libellé métier
n'est imprimé. Usage : uv run python -m examples.profile_inputs
"""

from collections import Counter
import csv
import json
from pathlib import Path
import time
from xml.etree import ElementTree as ET
from xml.parsers import expat
from zipfile import ZipFile

from openpyxl.utils.datetime import from_excel

from reconciliation.loaders.sage import load_sage

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def profile_atlas(path, output):
    start = time.perf_counter()
    report = {"sheets": [], "statuses": Counter(), "years": Counter(), "currencies": Counter(),
              "rows": 0, "duplicate_ids": 0, "missing_ids": 0, "sent": 0, "confirmed": 0,
              "pending": 0, "pending_missing": Counter()}
    ids = set()
    pending_file = (output / "atlas_pending.csv").open("w", encoding="utf-8", newline="")
    writer = None
    with ZipFile(path) as archive:
        strings = []
        with archive.open("xl/sharedStrings.xml") as stream:
            parser = ET.iterparse(stream, events=("start", "end"))
            _, root = next(parser)
            for event, element in parser:
                if event == "end" and element.tag == NS + "si":
                    strings.append("".join(t.text or "" for t in element.iter(NS + "t")))
                    root.clear()
        print(f"Atlas : dictionnaire de chaînes chargé en {time.perf_counter()-start:.1f}s", flush=True)
        for sheet in [i.filename for i in archive.infolist() if i.filename.startswith("xl/worksheets/sheet") and i.filename.endswith(".xml")]:
            info = {"sheet": sheet, "rows": 0, "headers": []}
            row, cell, value, kind, capture = {}, "", [], "", False

            def on_start(name, attrs):
                nonlocal row, cell, value, kind, capture
                if name == "row":
                    row = {}
                elif name == "c":
                    cell = "".join(c for c in attrs.get("r", "") if c.isalpha())
                    kind, value = attrs.get("t", ""), []
                elif name in ("v", "t"):
                    capture = True

            def on_text(text):
                if capture:
                    value.append(text)

            def on_end(name):
                nonlocal capture, writer
                if name in ("v", "t"):
                    capture = False
                elif name == "c":
                    raw = "".join(value)
                    row[cell] = strings[int(raw)] if kind == "s" and raw else raw
                elif name == "row":
                    if not info["headers"]:
                        info["headers"] = dict(row)
                        return
                    if not any(row.values()):
                        return
                    info["rows"] += 1
                    report["rows"] += 1
                    record = {header: row.get(col, "") for col, header in info["headers"].items()}
                    identifier = record.get("Id", "")
                    if not identifier:
                        report["missing_ids"] += 1
                    elif identifier in ids:
                        report["duplicate_ids"] += 1
                        return
                    ids.add(identifier)
                    status = record.get("Statut BAP", "").replace("\u00a0", " ").replace("\u202f", " ").strip()
                    report["statuses"][status] += 1
                    report["years"][record.get("Année", "")] += 1
                    report["currencies"][record.get("Devise", "")] += 1
                    if status == "Envoyé SAGE":
                        report["sent"] += 1
                        if all(record.get(k, "").strip() for k in ("N° pièce SAGE", "Date comptable", "Total charges SAGE (€)")):
                            report["confirmed"] += 1
                        else:
                            report["pending"] += 1
                            for key in ("Code projet", "Libellé ATLAS", "Code tiers SAGE", "N° BAP (SAGE)", "Total charges projet (€)"):
                                if not record.get(key, "").strip():
                                    report["pending_missing"][key] += 1
                            for key in ("Date comptable", "Date début", "Date fin", "Date d'import", "Modifié le"):
                                if record.get(key):
                                    try:
                                        record[key] = from_excel(float(record[key])).isoformat()
                                    except (ValueError, OverflowError):
                                        pass
                            if writer is None:
                                writer = csv.DictWriter(pending_file, fieldnames=list(record), extrasaction="ignore")
                                writer.writeheader()
                            writer.writerow(record)
                    if report["rows"] % 100000 == 0:
                        print(f"Atlas : {report['rows']} lignes parcourues, {report['pending']} à rechercher", flush=True)

            parser = expat.ParserCreate()
            parser.StartElementHandler, parser.EndElementHandler = on_start, on_end
            parser.CharacterDataHandler = on_text
            with archive.open(sheet) as stream:
                while block := stream.read(1024 * 1024):
                    parser.Parse(block, False)
                parser.Parse(b"", True)
            report["sheets"].append(info)
    pending_file.close()
    report["seconds"] = round(time.perf_counter() - start, 2)
    return report


def main():
    output = Path("data/analysis")
    output.mkdir(exist_ok=True)
    start = time.perf_counter()
    sage = load_sage("data/inputs/ZLISTPJT.csv")
    sage_report = {"rows": len(sage), "columns": list(sage), "load_summary": sage.attrs["load_summary"],
                   "typing_issues": sage.attrs["typing_issues"], "missing": sage.isna().sum().to_dict(),
                   "seconds": round(time.perf_counter()-start, 2),
                   "years": sage["Date comptable"].dt.year.value_counts(dropna=False).to_dict()}
    (output / "sage_profile.json").write_text(json.dumps(sage_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Sage : {len(sage)} lignes, {sage_report['seconds']}s ; schéma et qualité enregistrés", flush=True)
    del sage
    atlas_report = profile_atlas(Path("data/inputs/JDD.xlsx"), output)
    (output / "atlas_profile.json").write_text(json.dumps(atlas_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in atlas_report.items() if k != "sheets"}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
