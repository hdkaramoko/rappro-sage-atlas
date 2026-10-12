"""Contrat JSONL versionné pour la validation métier dans l'application Django."""

import hashlib
import json
import os
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from reconciliation.exporters.excel import canonical_atlas
from reconciliation.matching.trace import json_value


INVENTORY_COLUMNS = ("Code projet", "Année", "Id", "Statut BAP", "Total charges projet (€)",
                     "Total charges SAGE (€)", "N° pièce SAGE", "Date comptable")


def export_review_bundle(atlas, sage, result, output_path, *, campaign_name=None,
                        scope="atlas-complet", source_paths=None, year=None,
                        controls=None, amount_field="total_sage_charges", tolerance="0.01"):
    """Un enregistrement par groupe, sources Atlas et lignes Sage complètes incluses."""
    target = Path(output_path).resolve()
    if target.suffix != ".jsonl":
        raise ValueError("Le fichier de validation doit porter l'extension .jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    from reconciliation_contract.atlas_context import ATLAS_CONTEXT, context_number
    canonical = canonical_atlas(atlas)
    for column in ATLAS_CONTEXT:
        canonical[column] = [context_number(json_value(value)) for value in atlas[column]] if column in atlas else None
    if controls is not None:
        from reconciliation_contract import EXTRA_INVENTORY
        for column in EXTRA_INVENTORY:
            if column not in canonical:
                canonical[column] = atlas[column] if column in atlas else None
    candidates = {g["group_id"]: g for g in result.attrs["sage_candidates"]}
    handle = NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False)
    temporary = Path(handle.name)
    count = 0
    try:
        with handle:
            def emit(payload):
                """Écrit un enregistrement JSON strict dans le fichier temporaire."""
                handle.write(json.dumps(json_value(payload), ensure_ascii=False, allow_nan=False) + "\n")

            now = datetime.now(timezone.utc).isoformat()
            version = 3 if controls is not None else 2
            emit({"type": "campaign", "schema_version": version,
                  "controls_available": controls is not None,
                  "amount_field": amount_field, "tolerance": tolerance,
                  "sage_amount_currency": "EUR",
                  "load_quality": {"atlas": atlas.attrs.get("load_summary", {}), "sage": sage.attrs.get("load_summary", {})},
                  "name": campaign_name or f"Rapprochement {year or 'toutes années'} — {now[:10]}",
                  "year": year,
                  "scope": scope, "generated_at": now,
                  "sources": {name: Path(path).name for name, path in (source_paths or {}).items()}})
            if version == 3:
                from reconciliation.multiples import INVENTORY, inventory_rows
                context_rows = canonical[list(ATLAS_CONTEXT)].itertuples(index=False, name=None)
                for row, values in zip(inventory_rows(atlas), context_rows, strict=True):
                    context = dict(zip(ATLAS_CONTEXT, values))
                    emit({"type": "inventory", "atlas": {**{column: row[field] for column, field in INVENTORY.items()}, **context}})
            else:
                columns = (*INVENTORY_COLUMNS, *ATLAS_CONTEXT)
                for values in canonical[list(columns)].itertuples(index=False, name=None):
                    emit({"type": "inventory", "atlas": dict(zip(columns, values))})
            for record in result.to_dict("records"):
                rows = canonical.iloc[list(record["atlas_source_positions"])].to_dict("records")
                for row in rows:
                    value = row.get("Date comptable")
                    if hasattr(value, "date") and str(value) != "NaT":
                        row["Date comptable"] = value.date().isoformat()
                project = str(rows[0]["Code projet"]).strip().upper()
                identity = [project, sorted(str(row["Id"]) for row in rows)]
                if year is not None:
                    identity.insert(1, year)
                key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
                evidence = []
                for candidate in record["candidate_ids"]:
                    group = candidates[candidate]
                    evidence.append({"id": candidate, "rows": sage.iloc[list(group["source_positions"])].to_dict("records")})
                if version == 3:
                    from reconciliation_contract import entry_from_sage
                    for candidate in evidence:
                        for row in candidate['rows']:
                            row['entry_ref'] = entry_from_sage(json_value(row))['ref']
                payload = {"type": "proposal", "schema_version": version, "key": key, "project": project,
                           "rule": record["match_rule"], "match_status": record["match_status"],
                           "sage_total": record["sage_amount"], "evidence": evidence, "atlas": rows}
                emit(payload)
                count += 1
            control_count = 0
            statuses = Counter()
            if controls is not None:
                for control in controls:
                    emit({"type": "control", "data": control})
                    control_count += 1
                    statuses[control['status']] += 1
            emit({"complete": count, "inventory_count": len(canonical), **({"control_count": control_count, "control_statuses": dict(statuses)} if version == 3 else {})})
            if version == 3:
                logging.info('Contrôles multiples : %s', dict(statuses))
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
