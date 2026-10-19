"""Schémas sources et paramètres de lecture centralisés."""

ATLAS_REQUIRED_COLUMNS = ("Id", "Code projet")
ATLAS_TEXT_COLUMNS = (
    "Id", "Bailleur", "Code projet", "Libellé projet", "Activité",
    "Code ligne budgétaire", "Libellé ligne budgetaire", "Libellé ATLAS",
    "Nom du tiers", "Nature de dépense (ATLAS)", "Libellé SAGE",
    "Code tiers SAGE", "Nature de dépense (SAGE)", "N° BAP (Atlas)",
    "N° BAP (SAGE)", "Statut BAP", "N° pièce SAGE", "Devise",
    "Ecart vérifié", "Commentaires sur écart", "Numéro d'import", "Modifié par",
)
ATLAS_DATE_COLUMNS = (
    "Date début", "Date fin", "Date comptable", "Date d'import", "Modifié le",
)
ATLAS_NUMERIC_COLUMNS = (
    "Total charges Atlas (en devise)", "Taux de change",
    "Total charges projet (€)", "Total charges SAGE (€)", "Ecart comptable",
)
ATLAS_INTEGER_COLUMNS = ("Année",)

SAGE_REQUIRED_COLUMNS = ("Projet", "Numéro pièce", "Date comptable")
SAGE_TEXT_COLUMNS = (
    "Projet", "Numéro pièce", "Journal", "N° de ligne comptable",
    "N° de ligne Analytique", "Comptes comptables", "Nature de dépenses",
    "Code TVA", "Libellé pièce", "Code Tiers - Tiers doc Orig", "Nom du Tiers",
    "Document Origine", "Référence", "Devise",
)
SAGE_DATE_COLUMNS = (
    "Date comptable", "Date création", "Date modification",
    "Date début de prestation", "Date fin de prestation",
)
SAGE_NUMERIC_COLUMNS = (
    "Taux de TVA", "Montant en devises", "Tx devises de la pièce cptble",
    "Charges (Dépenses)", "Produits (Recettes)",
)
SAGE_INTEGER_COLUMNS = ()
SAGE_CSV_SEPARATOR = None  # Détection limitée à ; et , sur l'en-tête.
SAGE_CSV_ENCODING = "utf-8-sig"
SAGE_CSV_FALLBACK_ENCODING = "cp1252"
SAGE_CSV_DECIMAL = ","

# Paramètres métier de l'étape 3.
ATLAS_STATUS_SENT_TO_SAGE = "Envoyé SAGE"
ATLAS_STATUS_ACCOUNTED = "Comptabilisé"
AMOUNT_TOLERANCE = 0.01
FUZZY_HIGH_THRESHOLD = 0.95
FUZZY_REVIEW_THRESHOLD = 0.85
MATCH_AMOUNT_CONFIDENCE = 0.90
MATCH_WITHOUT_LABEL_CONFIDENCE = 0.70
MATCHING_FULL_KEY = ("project_code", "label", "third_party_code", "matching_reference")
MATCHING_BLOCK_KEY = ("project_code", "third_party_code", "matching_reference")
MATCHING_SOURCE_COLUMNS = {
    "ATLAS": {
        "matching_reference": "N° BAP (SAGE)",
        "third_party_code": "Code tiers SAGE",
        "matching_amount": "Total charges projet (€)",
        "source_status": "Statut BAP",
        "confirmed_amount": "Total charges SAGE (€)",
    },
    "SAGE": {
        "third_party_code": "Code Tiers - Tiers doc Orig",
        "matching_amount": "Charges (Dépenses)",
    },
}

# Aucun choix implicite pour les montants et la référence Atlas à confirmer.
ATLAS_CANONICAL_COLUMNS = {
    "project_code": "Code projet",
    "reference": None,
    "accounting_document": "N° pièce SAGE",
    "amount": None,
    "currency": "Devise",
    "accounting_date": "Date comptable",
    "label": "Libellé ATLAS",
    "third_party": "Nom du tiers",
}
SAGE_CANONICAL_COLUMNS = {
    "project_code": "Projet",
    "reference": "Référence",
    "accounting_document": "Numéro pièce",
    "amount": None,
    "currency": "Devise",
    "accounting_date": "Date comptable",
    "label": "Libellé pièce",
    "third_party": "Nom du Tiers",
}

# Validation métier : activation explicite, après tous les contrôles du moteur.
AUTO_VALIDATION = {"enabled": True, "statuses": ["MATCH_CONFIRMED_ATLAS", "MATCH_EXACT", "MATCH_AMOUNT"]}

# Diagnostic par défaut ; ACTIVE autorise la validation collective explicite.
PIECE_COHERENCE = {"enabled": True, "mode": "ACTIVE"}
