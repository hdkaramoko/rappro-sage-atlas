from datetime import date
from collections import Counter

from django import template

from reconciliation.presentation import RULE_LABELS, money

register = template.Library()
register.filter("euros", money)


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
