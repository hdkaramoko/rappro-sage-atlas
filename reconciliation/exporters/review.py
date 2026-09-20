"""Contrat JSONL versionné pour la validation métier dans l'application Django."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from reconciliation.exporters.excel import canonical_atlas
from reconciliation.matching.trace import json_value


INVENTORY_COLUMNS = ("Code projet", "Année", "Id", "Statut BAP", "Total charges projet (€)",
                     "Total charges SAGE (€)", "N° pièce SAGE", "Date comptable")


def export_review_bundle(atlas, sage, result, output_path, *, campaign_name=None,
                        scope="atlas-complet", source_paths=None):
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
            def emit(payload):
                handle.write(json.dumps(json_value(payload), ensure_ascii=False, allow_nan=False) + "\n")

            now = datetime.now(timezone.utc).isoformat()
            emit({"type": "campaign", "schema_version": 2,
                  "name": campaign_name or f"Rapprochement {now[:10]}",
                  "scope": scope, "generated_at": now,
                  "sources": {name: Path(path).name for name, path in (source_paths or {}).items()}})
            for values in canonical[list(INVENTORY_COLUMNS)].itertuples(index=False, name=None):
                emit({"type": "inventory", "atlas": dict(zip(INVENTORY_COLUMNS, values))})
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
                payload = {"type": "proposal", "schema_version": 2, "key": key, "project": project,
                           "rule": record["match_rule"], "match_status": record["match_status"],
                           "sage_total": record["sage_amount"], "evidence": evidence, "atlas": rows}
                emit(payload)
                count += 1
            emit({"complete": count, "inventory_count": len(canonical)})
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
