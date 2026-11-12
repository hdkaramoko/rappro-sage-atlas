"""Adaptation pandas de l'inventaire Sage complet, indépendant du préfiltre."""

from collections.abc import Iterator

from reconciliation.matching.trace import json_value
from reconciliation_contract import entry_from_sage
from reconciliation_contract import digest, text
from reconciliation_contract.sage_inventory import inventory_record


def inventory_records(sage, policy: dict) -> Iterator[dict]:
    """Parcourt le DataFrame Sage filtré/dédupliqué sans copie globale.

    `sage` est la population complète après le loader, `policy` une politique
    d'exclusion validée. Chaque résultat signé conserve une vraie écriture,
    y compris exclue ou sans candidat Atlas. Les collisions restent visibles.
    L'empreinte source avant typage et les attributs comptables complémentaires
    différencient les sources distinctes ayant la même identité canonique.
    """
    for values in sage.itertuples(index=False, name=None):
        raw = json_value(dict(zip(sage.columns, values)))
        fingerprint = raw.get("_sage_source_fingerprint")
        if not fingerprint:
            from reconciliation.config import SAGE_CANONICAL_COLUMNS
            fingerprint = digest({k: v for k, v in raw.items()
                                  if k not in SAGE_CANONICAL_COLUMNS and k != "source" and not k.startswith("_")})
        attributes = {column: text(raw.get(column)) for column in
                      ("Référence", "Comptes comptables", "Nature de dépenses", "Code TVA", "Document Origine")}
        yield inventory_record(entry_from_sage(raw), policy, source_fingerprint=fingerprint, attributes=attributes)
