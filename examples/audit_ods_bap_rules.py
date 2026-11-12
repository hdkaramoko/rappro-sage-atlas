"""Vérification ciblée en lecture seule des deux cas réels, sans import ou recalcul de campagne."""

import json
from pathlib import Path
import sqlite3
from time import perf_counter

from reconciliation_contract import control_identity, digest, entry_from_sage
from reconciliation_contract.fuzzy_safety import FuzzySafety
from reconciliation_contract.matching_policy import precise_source
from reconciliation_contract.ods_party import party_scope
from reconciliation_contract.sage_inventory import consolidate


def audit(database):
    """Compare les clés ODG et le garde BAP sur les seuls projets utiles ; retourne des statistiques non sensibles."""
    connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    campaign_id, = connection.execute("SELECT id FROM reconciliation_campaign WHERE is_current=1").fetchone()
    sources = [json.loads(row[0]) for row in connection.execute(
        "SELECT data FROM reconciliation_campaigninventory WHERE campaign_id=? AND source_id IN (?,?,?)",
        (campaign_id, "1617252", "1617253", "1617254"))]
    records = [json.loads(row[0]) for row in connection.execute(
        "SELECT data FROM reconciliation_campaignsageentry WHERE campaign_id=? AND project_code=? AND document IN (?,?,?)",
        (campaign_id, "22SSE0C372", "ODG0126021231", "ODG0126021232", "ODG0126021233"))]
    report = {"ods": {}, "bap": {}}
    for enabled in (False, True):
        with party_scope(enabled):
            identities, left, right = {}, {}, {}
            for source in sources:
                identity = control_identity(source)
                key = digest(identity)
                identities[key] = identity
                left.setdefault(key, []).append(source)
            for record in records:
                identity = control_identity(record["entry"], sage=True)
                key = digest(identity)
                identities[key] = identity
                right.setdefault(key, []).append(record)
            outcomes = [consolidate(identity, left.get(key, []), right.get(key, []), []) for key, identity in identities.items()]
            report["ods"]["after" if enabled else "before"] = {"groups": len(outcomes),
                "states": [row["state"] for row in outcomes],
                "atlas_lines": len(sources), "sage_entries": len(records)}
    project = "20GDH0C171"
    atlas = [json.loads(row[0]) for row in connection.execute(
        "SELECT data FROM reconciliation_campaigninventory WHERE campaign_id=? AND project_code=? AND json_extract(data,'$.bap_status')=?",
        (campaign_id, project, "Comptabilisé"))]
    source = entry = None
    for raw, group in connection.execute(
        "SELECT r.source,g.data FROM reconciliation_campaignreview r JOIN reconciliation_campaigngroup g ON g.id=r.group_id "
        "JOIN projects_project p ON p.id=r.project_id WHERE r.campaign_id=? AND p.code=?", (campaign_id, project)):
        raw, group = json.loads(raw), json.loads(group)
        canonical = precise_source(raw, group["matching_source_amounts"]) if group.get("matching_source_amounts") else raw
        atlas.append(canonical)
        if canonical["source_id"] == "1710939":
            source = canonical
            proof = group["evidence"][0]["rows"][0]
            entry = {**entry_from_sage(proof), "matching_reference": proof.get("Référence")}
    sage = []
    for raw, in connection.execute("SELECT data FROM reconciliation_campaignsageentry WHERE campaign_id=? AND project_code=?", (campaign_id, project)):
        record = json.loads(raw)
        sage.append({**record["entry"], "matching_reference": record.get("attributes", {}).get("Référence")})
    from decimal import Decimal
    begin = perf_counter()
    guard = FuzzySafety(atlas, sage, precise_atlas=atlas)
    report["bap"].update(atlas_rows=len(atlas), sage_entries=len(sage), index_seconds=perf_counter()-begin)
    for enabled in (False, True):
        begin = perf_counter()
        passed = 0
        reason = ""
        for _ in range(1000):
            try:
                guard.verify_bap_balance(source, entry, tolerance=Decimal("0.05"), precise=True, distinct_accounted=enabled)
                passed += 1
            except ValueError as error:
                reason = str(error)
        report["bap"]["after" if enabled else "before"] = {"passed": passed, "checks": 1000,
            "seconds": round(perf_counter()-begin, 6), "reason": reason}
    connection.close()
    return report


if __name__ == "__main__":
    print(json.dumps(audit("app-suivi-reconciliation/db.sqlite3"), ensure_ascii=True))
