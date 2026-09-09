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
    "Nombre d'unités", "Total charges Atlas (en devise)", "Taux de change",
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
