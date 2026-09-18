from datetime import date

from django import template

from reconciliation.presentation import RULE_LABELS, money

register = template.Library()
register.filter("euros", money)


@register.filter
def integer_fr(value):
    return f"{int(value or 0):,}".replace(",", "\u202f")


@register.filter
def rule_label(value):
    return RULE_LABELS.get(value, value)


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
