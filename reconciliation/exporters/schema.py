"""Intitulés canoniques du classeur de restitution, dans l'ordre métier."""

ATLAS_EXPORT_COLUMNS = (
    "Id", "Code projet", "Libellé projet", "Année", "Activité", "Code ligne budgétaire",
    "Libellé ligne budgétaire", "Libellé ATLAS", "Nature de dépense (ATLAS)",
    "Code tiers SAGE", "Nom du tiers", "N° BAP (SAGE)", "Statut BAP", "Lieu de paiement",
    "Moyen de paiement", "Date comptable", "N° pièce SAGE", "Total charges projet (€)",
    "Total charges SAGE (€)",
)
ATLAS_EXPORT_ALIASES = {"Libellé ligne budgétaire": ("Libellé ligne budgetaire",)}
RESULT_COLUMNS = {
    "match_status": "Statut du rapprochement",
    "match_rule": "Règle retenue",
    "target_status": "Statut BAP proposé",
    "requires_review": "Revue nécessaire",
    "confidence": "Confiance",
    "label_similarity": "Similarité du libellé",
    "atlas_group_id": "Groupe Atlas",
    "atlas_source_positions": "Positions Atlas (base 0)",
    "atlas_row_count": "Nombre de lignes Atlas du groupe",
    "sage_row_count": "Nombre de lignes Sage du groupe",
    "cardinality_match": "Cardinalités identiques",
    "atlas_amount": "Montant agrégé Atlas (€) — non additionnable",
    "sage_amount": "Montant Sage proposé du groupe (€) — non additionnable",
    "amount_difference": "Écart du groupe Atlas - Sage (€) — non additionnable",
    "sage_document_number": "N° pièce Sage proposé",
    "sage_accounting_date": "Date comptable Sage proposée",
    "sage_document_numbers": "Pièces Sage distinctes du groupe",
    "sage_accounting_dates": "Dates Sage distinctes du groupe",
    "sage_group_id": "Groupe Sage",
    "sage_source_ids": "Positions Sage (base 0)",
    "candidate_count": "Nombre de candidats Sage",
    "candidate_ids": "Groupes Sage candidats",
    "candidate_scores": "Scores des candidats",
    "reason": "Motif du résultat",
}
TRACE_LABELS = (
    "Groupe Atlas", "Id Atlas du groupe", "Étape", "Issue", "Motif",
    "Candidats avant", "Candidats après", "Groupe Sage", "Code projet",
    "Code tiers", "BAP / Référence", "Libellé Atlas comparé", "Libellé Sage comparé",
    "Montant agrégé Atlas (€)", "Montant agrégé Sage (€)", "Écart Atlas - Sage (€)",
    "Nombre de lignes Atlas", "Nombre de lignes Sage", "Similarité du libellé",
    "Positions Sage (base 0)", "Pièces Sage", "Dates Sage",
)
