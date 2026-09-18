"""Contrat JSONL versionné pour la validation métier dans l'application Django."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from reconciliation.exporters.excel import canonical_atlas
from reconciliation.matching.trace import json_value


def export_review_bundle(atlas, sage, result, output_path):
    """Un enregistrement par groupe, sources Atlas et lignes Sage complètes incluses."""
    target = Path(output_path).resolve()
    if target.suffix != ".jsonl":
        raise ValueError("Le fichier de validation doit porter l'extension .jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    canonical = canonical_atlas(atlas)
    candidates = {g["group_id"]: g for g in result.attrs["sage_candidates"]}
    handle = NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False)
    temporary = Path(handle.name)
    count = 0
    try:
        with handle:
            for record in result.to_dict("records"):
                rows = canonical.iloc[list(record["atlas_source_positions"])].to_dict("records")
                for row in rows:
                    value = row.get("Date comptable")
                    if hasattr(value, "date") and str(value) != "NaT":
                        row["Date comptable"] = value.date().isoformat()
                project = str(rows[0]["Code projet"]).strip().upper()
                key = hashlib.sha256(json.dumps([project, sorted(str(row["Id"]) for row in rows)], ensure_ascii=False).encode()).hexdigest()
                evidence = []
                for candidate in record["candidate_ids"]:
                    group = candidates[candidate]
                    evidence.append({"id": candidate, "rows": sage.iloc[list(group["source_positions"])].to_dict("records")})
                payload = {"schema_version": 1, "key": key, "project": project,
                           "rule": record["match_rule"], "match_status": record["match_status"],
                           "sage_total": record["sage_amount"], "evidence": evidence, "atlas": rows}
                handle.write(json.dumps(json_value(payload), ensure_ascii=False, allow_nan=False) + "\n")
                count += 1
            handle.write(json.dumps({"complete": count}) + "\n")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
