from datetime import date
from collections import Counter

from django import template

from reconciliation.presentation import RULE_LABELS, money

register = template.Library()
register.filter("euros", money)


@register.filter
def accounting_label(value):
    """Traduit un état de cadrage stocké ; retourne un libellé explicite si non calculable."""
    return {"CADRE": "Cadré", "NON_CADRE": "Non cadré", "INSUFFISANT": "Données insuffisantes"}.get(value, "Données insuffisantes")


@register.filter
def signed_euros(value):
    """Formate un écart EUR en français avec signe positif visible, sans changer son montant."""
    from decimal import Decimal
    return ("+" if value is not None and Decimal(str(value)) > 0 else "") + money(value)


@register.filter
def global_state_label(value):
    """Traduit l'état courant de contrôle en libellé métier ; aucune mutation."""
    return {"EQUILIBRE": "Équilibré", "ECART": "Écart", "INDETERMINE": "À revoir", "EXCLU": "Exclu"}.get(value, "À revoir")


@register.filter
def business_action_label(value):
    """Traduit le type d'événement Lot 2 sans exposer de structure technique."""
    return {"CORRECTION": "Correction enregistrée", "CORRECTION_CANCEL": "Correction annulée", "LINK": "Rapprochement manuel confirmé",
            "UNLINK": "Rapprochement manuel annulé", "DECISION": "Décision de rapprochement",
            "CARRY": "Actions reprises automatiquement", "CARRY_PENDING": "Reprise à confirmer"}.get(value, "Action métier")


@register.filter
def adjustment_reason_label(value):
    """Traduit un motif de correction centralisé ; retourne un tiret si absent."""
    from reconciliation.models import AtlasAdjustment
    return dict(AtlasAdjustment.Reason.choices).get(value, "—")


@register.filter
def business_decision_label(value):
    """Traduit l'état de décision stocké dans un audit métier ; aucune modification."""
    return {"VALIDATED": "Confirmé", "REJECTED": "Refusé", "DRAFT": "À valider"}.get(value, "—")


@register.simple_tag
def piece_comparison(data):
    """Regroupe les preuves conservées, sans recalculer la décision métier."""
    from reconciliation_contract import money as decimal_amount
    from reconciliation_contract.piece_coherence import identifier

    counts = []
    for source in ("atlas", "sage"):
        counts.append(Counter((identifier(row.get("third_party")), identifier(row.get("bap")),
                               decimal_amount(row.get("amount"))) for row in data.get(source, [])))
    left, right = counts
    rows = []
    for key in sorted(left.keys() | right.keys(), key=lambda k: (k[0], k[1], k[2] is None, k[2] or 0)):
        third_party, bap, amount = key
        a, s = left[key], right[key]
        incomplete = not third_party or not bap or amount is None
        label = ("Champ manquant" if incomplete else "Absent dans X3" if not s
                 else "Absent dans Atlas" if not a else "Multiplicité différente" if a != s
                 else "Concordant")
        rows.append({"third_party": third_party, "bap": bap,
                     "amount": format(amount, "f").replace(".", ",") if amount is not None else None,
                     "atlas_count": a, "sage_count": s, "difference": a - s,
                     "source": "Atlas et SAGE" if a and s else "Atlas" if a else "SAGE",
                     "label": label, "tone": "warning" if incomplete or a != s else "success"})
    return rows


@register.filter
def piece_label(value):
    return {
        "PIECE_RECONCILED": "Pièce cohérente avec SAGE",
        "PIECE_AMBIGUOUS": "Totaux cohérents, écritures à examiner",
        "PIECE_MISMATCH": "Incohérence constatée",
        "NOT_CHECKED": "Contrôle non réalisé ou données insuffisantes",
        "MATCHED": "Tiers, BAP, montants et répétitions concordants",
        "INSUFFICIENT": "Données insuffisantes pour conclure",
        "MISMATCH": "Correspondances individuelles incohérentes",
    }.get(value, "Résultat non disponible")


@register.filter
def integer_fr(value):
    return f"{int(value or 0):,}".replace(",", "\u202f")


@register.filter
def rule_label(value):
    return RULE_LABELS.get(value, value)


@register.filter
def multiple_label(value):
    """Traduit les codes du contrat en libellés métier lisibles dans les écrans."""
    return {
        "EXCESS": "Excédent potentiel",
        "BALANCED": "Équilibré",
        "SHORTFALL": "Atlas inférieur à SAGE",
        "UNKNOWN": "Données insuffisantes / ambiguës",
        "TO_REVIEW": "À examiner",
        "CONFIRMED": "Suspicion confirmée",
        "DISMISSED": "Suspicion écartée",
    }.get(value, value)


@register.filter
def date_fr(value):
    if not value:
        return "—"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return value


@register.simple_tag(takes_context=True)
def query_replace(context, **changes):
    query = context["request"].GET.copy()
    for key, value in changes.items():
        query[key] = value
    return "?" + query.urlencode()


@register.simple_tag(takes_context=True)
def page_link(context, parameter, number):
    """Construit un lien de pagination en préservant les autres filtres et pages.

    `parameter` est fourni par le template (page ou sage_page), `number` par
    Paginator. Copie le GET, retourne l'URL relative encodée, sans effet de bord.
    """
    query = context["request"].GET.copy()
    query[parameter] = number
    return "?" + query.urlencode()
