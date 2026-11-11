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
                        controls=None, amount_field="total_sage_charges", tolerance="0.01",
                        include_sage_inventory=False, excluded_prefixes=None):
    """Publie atomiquement un JSONL v2/v3 à partir des DataFrames et du résultat.

    `controls` est un itérateur v3 ; `include_sage_inventory` déclare la
    capacité sage_inventory_v1 et exige v3. `excluded_prefixes` est une liste
    stricte, vide par défaut/configuration. L'inventaire Sage complet est
    parcouru en flux avant les propositions. Une empreinte SHA256 certifie
    tous les enregistrements avant le marqueur final. Retourne le Path publié ;
    ValueError/OSError annulent le temporaire sans remplacer la sortie précédente.
    Les charges sont en EUR, `tolerance` est une chaîne décimale en euros.
    Le marqueur validation_policy active les seules nouvelles campagnes v3.
    Les autorisations Exact multilignes sont publiées après preuve bijective ;
    un groupe ambigu conserve sa proposition mais aucune autorisation AUTO.
    En v3, Libellé SAGE Atlas est transmis séparément dans l'inventaire et les
    propositions, avec une politique ODS explicite ; le matching reste sur ATLAS.
    Les AUTO structurées (fuzzy, sans libellé, BAP, individuel) exigent v3 et une unicité sur les inventaires entiers,
    indépendamment des candidats retenus par la similarité du libellé.
    Les références BAP enrichissent uniquement les index privés ; les preuves
    signées restent inchangées et leurs charges sont déjà exprimées en EUR.
    Les montants d'autorisation sont sommés en Decimal depuis les sources,
    afin de ne pas transporter les résidus des agrégats flottants du matching.
    """
    from reconciliation_contract.sage_inventory import CAPABILITY, exclusion_policy
    from reconciliation_contract import ODS_LABEL_POLICY
    from reconciliation import config
    if include_sage_inventory and controls is None:
        raise ValueError("L'inventaire Sage exige les contrôles v3")
    policy = exclusion_policy(config.SAGE_EXCLUDED_PREFIXES if excluded_prefixes is None else excluded_prefixes)
    from reconciliation.auto_validation import validate_config, proposal_metadata
    options = validate_config()
    from reconciliation.piece_coherence import build_piece_checks
    from reconciliation_contract.piece_coherence import identifier
    piece_checks = build_piece_checks(atlas, sage)
    from reconciliation import config
    piece_active = config.PIECE_COHERENCE["enabled"] and config.PIECE_COHERENCE["mode"] == "ACTIVE"
    if piece_active and controls is None:
        raise ValueError("L'activation collective exige un export v3 avec contrôles SAGE")
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
        canonical["Libellé SAGE"] = atlas["Libellé SAGE"].reset_index(drop=True) if "Libellé SAGE" in atlas else None
        for column in EXTRA_INVENTORY:
            if column not in canonical:
                canonical[column] = atlas[column] if column in atlas else None
        for column, origin in (("Total charges SAGE (€)", "_total_sage_decimal"),
                               ("Total charges projet (€)", "_total_project_decimal")):
            if origin in atlas:
                canonical[column] = atlas[origin]
    candidates = {g["group_id"]: g for g in result.attrs["sage_candidates"]}
    from reconciliation_contract.fuzzy_safety import STRUCTURED_RULES, FuzzySafety
    from reconciliation.multiples import inventory_rows
    from reconciliation_contract import entry_from_sage, money
    fuzzy_atlas = list(inventory_rows(atlas)) if result["match_rule"].isin(STRUCTURED_RULES).any() else []
    for row, bap in zip(fuzzy_atlas, canonical["N° BAP (SAGE)"] if fuzzy_atlas else []):
        row["sage_bap_number"] = json_value(bap)
    fuzzy_rows = (json_value(dict(zip(sage.columns, values))) for values in sage.itertuples(index=False, name=None))
    fuzzy_safety = FuzzySafety(fuzzy_atlas, ({**entry_from_sage(raw), "matching_reference": raw.get("Référence")}
        for raw in fuzzy_rows)) if fuzzy_atlas else None
    handle = NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False)
    temporary = Path(handle.name)
    count = 0
    stream_hash = hashlib.sha256()
    try:
        with handle:
            def emit(payload):
                """Écrit le dictionnaire JSON et signe les octets UTF-8 hors marqueur final."""
                line = json.dumps(json_value(payload), ensure_ascii=False, allow_nan=False) + "\n"
                handle.write(line)
                if "complete" not in payload:
                    stream_hash.update(line.encode("utf-8"))

            now = datetime.now(timezone.utc).isoformat()
            version = 3 if controls is not None else 2
            emit({"type": "campaign", "schema_version": version,
                  **({"validation_policy": "confirmed-exact-v2", "ods_label_policy": ODS_LABEL_POLICY} if version == 3 else {}),
                  **({"capabilities": [CAPABILITY], "sage_exclusions": policy} if include_sage_inventory else {}),
                  "piece_coherence_mode": "ACTIVE" if piece_active else "DIAGNOSTIC",
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
            sage_count = 0
            if include_sage_inventory:
                from reconciliation.sage_inventory import inventory_records
                for data in inventory_records(sage, policy):
                    emit({"type": "sage_inventory", "data": data})
                    sage_count += 1
            for values in result.itertuples(index=False, name=None):
                record = dict(zip(result.columns, values))
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
                for candidate in evidence:
                    for row in candidate["rows"]:
                        if "_charges_decimal" in row:
                            row["Charges (Dépenses)"] = row.pop("_charges_decimal")
                        row.pop("_sage_source_fingerprint", None)
                if version == 3:
                    from reconciliation_contract import entry_from_sage
                    for candidate in evidence:
                        for row in candidate['rows']:
                            row['entry_ref'] = entry_from_sage(json_value(row))['ref']
                payload = {"type": "proposal", "schema_version": version, "key": key, "project": project,
                           "rule": record["match_rule"], "match_status": record["match_status"],
                           "sage_total": record["sage_amount"], "evidence": evidence, "atlas": rows}
                authorization = record.copy()
                if record["match_rule"] != "MATCH_CONFIRMED_ATLAS":
                    atlas_amounts = [money(row.get("Total charges projet (€)")) for row in rows]
                    sage_amounts = [money(row.get("Charges (Dépenses)")) for candidate in evidence for row in candidate["rows"]]
                    authorization["atlas_amount"] = sum(atlas_amounts, money(0)) if atlas_amounts and all(v is not None for v in atlas_amounts) else None
                    authorization["sage_amount"] = sum(sage_amounts, money(0)) if sage_amounts and all(v is not None for v in sage_amounts) else None
                metadata = proposal_metadata(authorization, options)
                if metadata and record["match_rule"] in STRUCTURED_RULES:
                    try:
                        proofs = [r for candidate in evidence for r in candidate["rows"]]
                        if version != 3 or not include_sage_inventory or len(rows) != 1 or len(proofs) != 1:
                            raise ValueError("Une preuve individuelle v3 est requise pour cette AUTO structurée")
                        check = fuzzy_safety.verify_bap_balance if record["match_rule"] == "MATCH_BAP" else fuzzy_safety.verify
                        check(fuzzy_atlas[record["atlas_source_positions"][0]],
                              {**entry_from_sage(json_value(proofs[0])), "matching_reference": proofs[0].get("Référence")})
                    except ValueError:
                        metadata = None
                if metadata and record["match_rule"] == "MATCH_EXACT" and len(rows) > 1:
                    from reconciliation_contract.exact_assignment import exact_bijection
                    try:
                        if version != 3:
                            raise ValueError("Les groupes Exact automatiques exigent v3")
                        exact_bijection(json_value(rows), json_value([r for candidate in evidence for r in candidate.get("rows", [])]))
                    except ValueError:
                        metadata = None
                if metadata:
                    payload["auto_validation"] = metadata
                if len(rows) == 1:
                    diagnostic = piece_checks.get((project, identifier(rows[0].get("N° pièce SAGE"))))
                    if diagnostic:
                        payload["piece_coherence"] = diagnostic
                if (piece_active and record["match_rule"] == "MATCH_CONFIRMED_ATLAS"
                        and payload.get("piece_coherence", {}).get("status") != "PIECE_RECONCILED"):
                    payload.pop("auto_validation", None)
                emit(payload)
                count += 1
            control_count = 0
            statuses = Counter()
            if controls is not None:
                for control in controls:
                    emit({"type": "control", "data": control})
                    control_count += 1
                    statuses[control['status']] += 1
            emit({"complete": count, "inventory_count": len(canonical),
                  **({"sage_inventory_count": sage_count, "stream_sha256": stream_hash.hexdigest()} if include_sage_inventory else {}),
                  **({"control_count": control_count, "control_statuses": dict(statuses)} if version == 3 else {})})
            if version == 3:
                logging.info('Contrôles multiples : %s', dict(statuses))
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
