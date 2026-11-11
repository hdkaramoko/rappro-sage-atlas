"""Derniers recours BAP puis individuel, sans reprendre une preuve déjà proposée."""

from bisect import bisect_left, bisect_right
from collections import defaultdict, Counter
from decimal import Decimal

from reconciliation import config
from reconciliation.multiples import inventory_rows
from reconciliation.matching.trace import json_value
from reconciliation.matching.models import UNMATCHED, MATCH_BAP, MATCH_INDIVIDUAL
from reconciliation.matching.results import base_result, apply_candidates
from reconciliation_contract import entry_from_sage, money, text


def block(row, *, sage=False):
    """Retourne projet/tiers/exercice/BAP normalisés, sans modifier la source.

    Les données canoniques portent leurs montants EUR ; une référence absente
    reste vide, jamais égale par défaut à une référence connue.
    """
    return (text(row.get("project_code")).upper(),
            text(row.get("third_party") if sage else row.get("sage_third_party_code")).upper(),
            row.get("fiscal_year"), text(row.get("matching_reference") if sage else row.get("sage_bap_number")).upper())


def candidate(rows, identifier):
    """Décrit des écritures individuelles au format des candidats déjà exportés.

    `rows` est une liste (position source, entrée canonique), `identifier` une
    clé locale stable. Conserve toutes les occurrences ; aucun écrit externe.
    """
    entries = [entry for _, entry in rows]
    amounts = [money(entry["amount"]) for entry in entries]
    return dict(group_id=identifier, row_count=len(rows),
        amount=sum(amounts, Decimal(0)) if all(v is not None for v in amounts) else None,
        source_positions=tuple(position for position, _ in rows), source_ids=tuple(position for position, _ in rows),
        documents=tuple(dict.fromkeys(e["document"] for e in entries if e["document"])),
        dates=tuple(dict.fromkeys(e["date"] for e in entries if e["date"])),
        document_count=sum(bool(e["document"]) for e in entries), date_count=sum(bool(e["date"]) for e in entries))


def final_matches(atlas_frame, sage_frame, results, catalogue, options, trace):
    """Complète uniquement les résultats UNMATCHED après la cascade historique.

    Indexe les sources en O(n log n), réserve les positions déjà proposées et
    les preuves Atlas comptabilisées/confirmées potentiellement consommées.
    Un BAP équilibré produit des paires individuelles si les montants déterminent
    une bijection ; sinon une proposition de groupe manuelle explicable. Les
    lignes restantes cherchent une écriture individuelle dans leur bloc sans
    exiger le total du groupe. Aucun choix arbitraire ni mutation des DataFrames.
    Retourne (résultats complets, candidats ajoutés), sans écriture fichier/SQL.
    L'export et Django recontrôlent l'unicité sur les populations complètes.
    """
    pending = {p for result in results if result.match_status == UNMATCHED for p in result.atlas_source_positions}
    if not pending:
        return results, []
    for result in results:
        if result.match_status == UNMATCHED:
            trace.add(result, MATCH_BAP, "EXECUTE", "Contrôle du bloc BAP résiduel après les règles prioritaires")
    atlas = list(inventory_rows(atlas_frame))
    for row, bap in zip(atlas, atlas_frame.get("N° BAP (SAGE)", [None] * len(atlas))):
        row["sage_bap_number"] = json_value(bap)
    used = {p for result in results if result.match_status != UNMATCHED for cid in result.candidate_ids
            for p in catalogue[cid]["source_positions"]}
    # Une preuve source sans identité analytique protège ses écritures plausibles.
    reserved = defaultdict(list)
    for row in atlas:
        if row["bap_status"] == "Comptabilisé" or row.get("sage_document_number") and row.get("accounting_date"):
            reserved[(row["project_code"], row.get("sage_document_number"), str(row.get("accounting_date") or "")[:10])].append(money(row.get("total_sage_charges")))
    by_block, source_entries, amounts_by_document = defaultdict(list), [], defaultdict(list)
    prefixes = set(config.SAGE_EXCLUDED_PREFIXES)
    for position, values in enumerate(sage_frame.itertuples(index=False, name=None)):
        raw = json_value(dict(zip(sage_frame.columns, values)))
        entry = {**entry_from_sage(raw), "matching_reference": raw.get("Référence")}
        amount = money(entry["amount"])
        source_entries.append((position, entry))
        if amount is not None:
            amounts_by_document[(entry["project_code"], entry["document"], entry["date"])].append(amount)
    uncertain_documents, reserved_amounts = set(), {}
    for document, claims in reserved.items():
        amounts = sorted(amounts_by_document.get(document, []))
        known = sorted(value for value in claims if value is not None)
        reserved_amounts[document] = known
        for value in claims:
            start = bisect_left(amounts, value - Decimal("0.01")) if value is not None else 0
            end = bisect_right(amounts, value + Decimal("0.01")) if value is not None else 0
            if value is None or not any(amount * value >= 0 for amount in amounts[start:end]):
                uncertain_documents.add(document)
                break
    for position, entry in source_entries:
        amount = money(entry["amount"])
        document = (entry["project_code"], entry["document"], entry["date"])
        claims = reserved_amounts.get(document, [])
        start = bisect_left(claims, amount - Decimal("0.01")) if amount is not None else 0
        end = bisect_right(claims, amount + Decimal("0.01")) if amount is not None else 0
        if (position in used or entry["document"][:3] in prefixes or amount is None
                or document in uncertain_documents or any(v * amount >= 0 for v in claims[start:end])):
            continue
        key = block(entry, sage=True)
        if all(v not in (None, "") for v in key[:3]):
            by_block[key].append((position, entry))
    left = defaultdict(list)
    for position in sorted(pending):
        key = block(atlas[position])
        if all(v not in (None, "") for v in key[:3]) and money(atlas[position]["total_project_charges"]) is not None:
            left[key].append(position)
    additions, output, handled = [], [], set()
    tolerance = min(Decimal(str(options.amount_tolerance)), Decimal("0.01"))

    def propose(positions, entries, rule, *, unique):
        """Ajoute une proposition traçable, jamais une réservation ou une décision métier.

        Les positions identifient les lignes sources, les entrées les preuves
        individuelles. `unique` atteste seulement la bijection de cette étape.
        Les contrôles d'unicité globaux restent obligatoires avant AUTO.
        """
        identifier = f"SAGE_RESIDUAL:{rule}:{','.join(str(p) for p, _ in entries)}"
        proof = candidate(entries, identifier)
        group = dict(group_id=f"ATLAS_RESIDUAL:{','.join(map(str, positions))}", source_ids=tuple(atlas[p]["source_id"] for p in positions),
            source_positions=tuple(positions), row_count=len(positions),
            amount=sum((money(atlas[p]["total_project_charges"]) for p in positions), Decimal(0)))
        result = base_result(group)
        apply_candidates(result, rule, [proof], (), options)
        if not unique:
            result.match_rule = rule
            result.requires_review = True
            result.reason = "BAP_INDIVIDUAL_AMBIGUITY" if rule == MATCH_BAP else "INDIVIDUAL_EVIDENCE_REVIEW"
        additions.append(proof); output.append(result); handled.update(positions)
        trace.add(result, rule, "RETENU" if unique else "A_EXAMINER", result.reason, before=len(entries), after=len(entries))

    for key, positions in left.items():
        entries = by_block.get(key, [])
        if not key[-1] or not entries:
            continue
        left_amounts = [money(atlas[p]["total_project_charges"]) for p in positions]
        right_amounts = [money(e["amount"]) for _, e in entries]
        if abs(sum(left_amounts, Decimal(0)) - sum(right_amounts, Decimal(0))) > tolerance:
            continue
        # Chercher au plus deux candidats suffit à constater une ambiguïté.
        ordered = sorted(entries, key=lambda item: money(item[1]["amount"]))
        amounts = [money(e["amount"]) for _, e in ordered]
        pairs = []
        for position, amount in zip(positions, left_amounts):
            low, high = bisect_left(amounts, amount - tolerance), bisect_right(amounts, amount + tolerance)
            matches = [item for item in ordered[low:min(high, low + 2)] if money(item[1]["amount"]) * amount >= 0]
            pairs.append(matches)
        claims = Counter(items[0][0] for items in pairs if len(items) == 1)
        bijective = len(positions) == len(entries) and all(len(items) == 1 and claims[items[0][0]] == 1 for items in pairs)
        if bijective:
            for position, matches in zip(positions, pairs):
                propose([position], matches, MATCH_BAP, unique=True)
        else:
            propose(positions, entries, MATCH_BAP, unique=False)
    indexes, by_prefix = {}, defaultdict(list)
    for key, entries in by_block.items():
        ordered = sorted(entries, key=lambda item: money(item[1]["amount"]))
        indexes[key] = ([money(e["amount"]) for _, e in ordered], ordered)
        by_prefix[key[:3]].extend(entries)
    prefix_indexes = {}
    for prefix, entries in by_prefix.items():
        ordered = sorted(entries, key=lambda item: money(item[1]["amount"]))
        prefix_indexes[prefix] = ([money(e["amount"]) for _, e in ordered], ordered)
    # Recherche individuelle résiduelle, seulement après la tentative BAP.
    reserved_positions = {p for c in additions for p in c["source_positions"]}
    for result in results:
        if result.match_status == UNMATCHED:
            remains = set(result.atlas_source_positions) - handled
            trace.add(result, MATCH_INDIVIDUAL, "EXECUTE" if remains else "NON_EXECUTE",
                      "Recherche des écritures individuelles restantes" if remains else "Proposition BAP déjà retenue")
    for key, positions in left.items():
        buckets = defaultdict(list)
        for position in positions:
            if position not in handled:
                buckets[money(atlas[position]["total_project_charges"])].append(position)
        for amount, remaining_positions in buckets.items():
            amounts, entries = indexes.get(key, ([], [])) if key[-1] else prefix_indexes.get(key[:3], ([], []))
            low, high = bisect_left(amounts, amount - tolerance), bisect_right(amounts, amount + tolerance)
            matches = [item for item in entries[low:high] if item[0] not in reserved_positions and money(item[1]["amount"]) * amount >= 0]
            if matches:
                # Tous les concurrents sont gardés dans les preuves ; aucun premier choix arbitraire.
                propose(remaining_positions, matches, MATCH_INDIVIDUAL,
                        unique=len(remaining_positions) == len(matches) == 1 and bool(key[-1]))
    remaining = []
    for result in results:
        if result.match_status != UNMATCHED or not set(result.atlas_source_positions).intersection(handled):
            remaining.append(result)
        else:
            for position in result.atlas_source_positions:
                if position not in handled:
                    remaining.append(base_result(dict(group_id=f"ATLAS_RESIDUAL:{position}", source_ids=(atlas[position]["source_id"],),
                        source_positions=(position,), row_count=1, amount=money(atlas[position]["total_project_charges"]))))
    return remaining + output, additions
