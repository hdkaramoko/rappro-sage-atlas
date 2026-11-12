"""Preuve bijective Exact partagée, sans dépendance Django ou pandas."""

from collections import defaultdict
from decimal import Decimal

from . import entry_from_sage, label, money, text
from .piece_coherence import identifier


def exact_bijection(atlas, proofs):
    """Associe chaque source Atlas à une écriture réelle par clé complète et montant.

    `atlas` et `proofs` sont les lignes sources brutes du JSONL. La clé projet,
    tiers, BAP et libellé doit être complète et identique. Les montants signés
    sont comparés au centime, sans appariement arbitraire des répétitions.
    Projet/exercice, date Atlas si présente et références sont contrôlés.
    Les champs de charges comparés sont en EUR selon le contrat ; la devise
    d'origine de l'opération n'entraîne ni veto ni conversion supplémentaire.
    Retourne {Id Atlas: entrée canonique} ; ValueError si incomplet ou ambigu.
    Fonction pure : ne réserve rien et ne modifie aucune source.
    """
    if len(atlas) < 2 or len(atlas) != len(proofs):
        raise ValueError("Cardinalités Exact incompatibles")
    buckets = defaultdict(list)
    refs = set()
    for raw in proofs:
        entry = entry_from_sage(raw)
        if not entry["identity_complete"] or raw.get("entry_ref") != entry["ref"] or entry["ref"] in refs:
            raise ValueError("Identité Sage absente ou répétée")
        refs.add(entry["ref"])
        key = (entry["project_code"], entry["third_party"], identifier(raw.get("Référence")), label(raw.get("Libellé pièce")))
        if not all(key) or money(entry["amount"]) is None:
            raise ValueError("Clé Exact ou montant Sage absent")
        buckets[key].append(entry)
    if len(buckets) != 1 or len({(e["document"], e["date"]) for entries in buckets.values() for e in entries}) != 1:
        raise ValueError("Clé ou pièce/date du groupe Exact non unique")
    result, used, totals = {}, set(), []
    for row in atlas:
        source_id = text(row.get("Id"))
        amount = money(row.get("Total charges projet (€)"))
        key = (identifier(row.get("Code projet")), identifier(row.get("Code tiers SAGE")),
               identifier(row.get("N° BAP (SAGE)")), label(row.get("Libellé ATLAS")))
        if not source_id or source_id in result or not all(key) or amount is None:
            raise ValueError("Identité Atlas ou clé Exact absente")
        matches = [e for e in buckets[key] if e["fiscal_year"] == row.get("Année")
                   and abs(money(e["amount"]) - amount) <= Decimal("0.01") and money(e["amount"]) * amount >= 0
                   and (not row.get("Date comptable") or str(row["Date comptable"])[:10] == e["date"])
                   and (not row.get("N° pièce SAGE") or identifier(row["N° pièce SAGE"]) == e["document"])]
        if len(matches) != 1 or matches[0]["ref"] in used:
            raise ValueError("Bijection Exact non unique")
        used.add(matches[0]["ref"])
        result[source_id] = matches[0]
        totals.append(amount)
    if abs(sum(totals) - sum(money(e["amount"]) for e in result.values())) > Decimal("0.01"):
        raise ValueError("Somme Exact divergente")
    return result
