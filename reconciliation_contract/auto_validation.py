"""Règles de rapprochement pouvant recevoir une autorisation automatique.

La demande JSONL transporte l'autorisation du moteur ; Django ne relit pas sa
configuration. Les deux côtés partagent les mêmes codes, sans dépendance ORM.
"""

AUTO_VALIDATION_RULES = frozenset({
    "MATCH_CONFIRMED_ATLAS", "MATCH_EXACT", "MATCH_AMOUNT",
    "MATCH_FUZZY_HIGH", "MATCH_FUZZY_REVIEW", "MATCH_WITHOUT_LABEL",
})
