"""Diagnostic source des Comptabilisé incomplets et références de revue manuelle."""

from datetime import date

from reconciliation_contract import money

LABELS = (
    (1, "Montant Sage Atlas absent ou invalide"),
    (2, "N° de pièce Sage absent"),
    (4, "Date comptable absente, invalide ou hors exercice"),
)


def missing_mask(data, fiscal_year):
    """Retourne le masque des trois défauts source ; zéro numérique est présent.

    Entrées : photographie Atlas et exercice attendu. Aucun effet de bord ni
    remplacement du statut ou des montants. Les dates ISO sont vérifiées.
    """
    if data.get("bap_status") != "Comptabilisé":
        return 0
    mask = 1 if money(data.get("total_sage_charges")) is None else 0
    if not str(data.get("sage_document_number") or "").strip():
        mask |= 2
    try:
        parsed = date.fromisoformat(str(data.get("accounting_date") or "")[:10])
        if parsed.year != fiscal_year:
            mask |= 4
    except ValueError:
        mask |= 4
    return mask


def missing_labels(inventory):
    """Retourne les libellés des défauts de cette source, sans lecture SQL supplémentaire."""
    mask = missing_mask(inventory.data, inventory.fiscal_year)
    return [label for bit, label in LABELS if mask & bit]


def comparison_amount(inventory):
    """Retourne la référence de revue, jamais un remplacement du montant source.

    Une correction active prévaut ; sinon le montant de la politique source est
    utilisé. Les charges projet servent seulement de repli aux incomplets.
    """
    from .business import source_amount

    adjustment = getattr(inventory, "adjustment", None)
    if adjustment and adjustment.active:
        return 0 if adjustment.reason == "DUPLICATE" else adjustment.amount
    amount = source_amount(inventory)
    if amount is None and missing_mask(inventory.data, inventory.fiscal_year):
        amount = money(inventory.data.get("total_project_charges"))
    return amount


def current_manual_link(inventory):
    """Vérifie la confirmation locale et sa version de correction, sans nouvelle décision.

    Retourne le lien courant ou None ; la création et les réservations restent
    exclusivement sous les verrous transactionnels Lot 2.
    """
    link = getattr(inventory, "inventory_match", None)
    adjustment = getattr(inventory, "adjustment", None)
    if (
        link
        and link.active
        and link.adjustment_version == (adjustment.version if adjustment else 0)
        and not (adjustment and adjustment.active and adjustment.reason == "DUPLICATE")
        and link.amount == comparison_amount(inventory)
    ):
        return link
    return None


def control_counts(campaign, keys):
    """Compte en une requête les diagnostics sources des seuls contrôles demandés."""
    from django.db.models import Count

    return dict(
        campaign.inventory.filter(present=True, control_key__in=keys, sage_missing_mask__gt=0)
        .values("control_key")
        .annotate(n=Count("pk"))
        .values_list("control_key", "n")
    )
