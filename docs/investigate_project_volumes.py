"""Read-only comparison of campaign project coverage."""
import collections
import hashlib
import json
import sqlite3
from pathlib import Path


def inspect(path):
    counts = collections.Counter()
    projects = collections.defaultdict(set)
    hashes = {}
    header = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            kind = row.get("type", "footer")
            counts[kind] += 1
            hashes.setdefault(kind, hashlib.sha256()).update(line.encode())
            if kind == "campaign":
                header = row
            if kind == "inventory":
                projects[kind].add(row["atlas"]["Code projet"])
            elif "project" in row:
                projects[kind].add(row["project"])
            elif kind == "sage_inventory":
                projects[kind].add(row["data"]["entry"]["project_code"])
    return {"counts": dict(counts), "projects": {k: len(v) for k, v in projects.items()},
            "hashes": {k: v.hexdigest() for k, v in hashes.items()},
            "header": header}


if __name__ == "__main__":
    results = {}
    for day in ("12", "13"):
        path = Path(f"data/outputs/campagne_{day}112026.jsonl")
        results[day] = inspect(path)
        print(day, json.dumps({k: v for k, v in results[day].items() if k != "header"}), flush=True)
    print("changed_header_fields", [k for k in results["13"]["header"]
                                    if results["12"]["header"].get(k) != results["13"]["header"][k]])
    db = sqlite3.connect("file:app-suivi-reconciliation/db.sqlite3?mode=ro", uri=True)
    for name, sql in {
        "visible_accounting": "select state,count(*) from reconciliation_accountingproject where project_code in (select code from projects_project) group by state",
        "missing_accounting": "select state,count(*) from reconciliation_accountingproject where project_code not in (select code from projects_project) group by state",
        "review_projects": "select count(distinct project_id) from reconciliation_reviewgroup",
        "missing_atlas": "select count(distinct project_code) from reconciliation_campaigninventory where project_code not in (select code from projects_project)",
        "atlas_accounting": "select state,count(*) from reconciliation_accountingproject where project_code in (select project_code from reconciliation_campaigninventory) group by state",
        "missing_atlas_accounting": "select state,count(*) from reconciliation_accountingproject where project_code in (select project_code from reconciliation_campaigninventory) and project_code not in (select code from projects_project) group by state",
    }.items():
        print(name, db.execute(sql).fetchall())
