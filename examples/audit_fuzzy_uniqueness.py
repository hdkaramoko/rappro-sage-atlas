"""Mesure en lecture seule les faux conflits de la campagne SQLite courante."""

import json
import sqlite3
from pathlib import Path
from time import perf_counter

from reconciliation_contract import entry_from_sage
from reconciliation_contract.fuzzy_safety import FuzzySafety


def audit(path):
    """Compare les contrôles sans modifier la base ni rejouer de validation."""
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    campaign, = connection.execute("SELECT id FROM reconciliation_campaign WHERE is_current=1").fetchone()
    start = perf_counter()
    atlas = [json.loads(row[0]) for row in connection.execute(
        "SELECT data FROM reconciliation_campaigninventory WHERE campaign_id=? AND present=1 "
        "AND json_extract(data,'$.bap_status')=?", (campaign, "Comptabilisé"))]
    targets = []
    for source, data, reasons in connection.execute(
        "SELECT r.source,g.data,r.reasons FROM reconciliation_campaignreview r "
        "JOIN reconciliation_campaigngroup g ON g.id=r.group_id WHERE r.campaign_id=?", (campaign,)):
        source, data = json.loads(source), json.loads(data)
        atlas.append(source)
        if data.get("rule") == "MATCH_FUZZY_HIGH":
            proofs = [raw for evidence in data.get("evidence", []) for raw in evidence.get("rows", [])]
            if len(proofs) == 1:
                entry = {**entry_from_sage(proofs[0]), "matching_reference": proofs[0].get("Référence")}
                targets.append((source, entry, bool(data.get("auto_validation")), json.loads(reasons)))
    sage = []
    for raw, in connection.execute("SELECT data FROM reconciliation_campaignsageentry WHERE campaign_id=?", (campaign,)):
        data = json.loads(raw)
        sage.append({**data["entry"], "matching_reference": data.get("attributes", {}).get("Référence")})
    loaded = perf_counter()
    baseline_atlas = FuzzySafety._index(atlas, sage=False)
    baseline_sage = FuzzySafety._index(sage, sage=True)
    baseline_seconds = perf_counter() - loaded
    del baseline_atlas, baseline_sage
    begin_index = perf_counter()
    guard = FuzzySafety(atlas, sage)
    indexed = perf_counter()
    result = {"targets": len(targets), "atlas": len(atlas), "sage": len(sage), "lifted": 0, "authorized_lifted": 0}
    pieces, lines, times = set(), [], {}
    outcomes = []
    for refined in (False, True):
        begin = perf_counter()
        passed = set()
        for position, (source, entry, authorized, reasons) in enumerate(targets):
            try:
                guard.verify(source, entry, distinct_accounted=refined)
                passed.add(position)
            except ValueError:
                pass
        outcomes.append(passed)
        times[str(refined)] = round(perf_counter() - begin, 4)
    for position in outcomes[1] - outcomes[0]:
        source, entry, authorized, reasons = targets[position]
        result["lifted"] += 1
        result["authorized_lifted"] += authorized
        pieces.add((entry["project_code"], entry["fiscal_year"], entry["document"]))
        lines.append(source["source_id"])
    result.update(pieces=len(pieces), real_case_lifted="1566314" in lines,
                  load_seconds=round(loaded-start, 3), index_before_seconds=round(baseline_seconds, 3),
                  index_seconds=round(indexed-begin_index, 3),
                  check_seconds=times, passed_before=len(outcomes[0]), passed_after=len(outcomes[1]), lines=lines)
    connection.close()
    return result


if __name__ == "__main__":
    import sys
    print(json.dumps(audit(sys.argv[1]), ensure_ascii=True))
