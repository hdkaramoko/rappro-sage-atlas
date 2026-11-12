"""Champs Atlas utiles à la validation, distincts des preuves de multiples."""

from decimal import Decimal, InvalidOperation

ATLAS_CONTEXT = {
    "Montant refacturables": "rebillable_amount",
    "Prix unitaire prévu": "planned_unit_price",
    "Nombre d'unités": "unit_count",
}
ATLAS_CONTEXT_ALIASES = {"Montant refacturables": ("Montant refacturable (€)",)}


def context_number(value):
    """Normalise sans arrondi ; absent reste nul, zéro reste zéro (six décimales maximum)."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    try:
        number = Decimal(text.replace(",", "."))
        if not number.is_finite() or abs(number) >= Decimal("1e18"):
            raise ValueError("Nombre non fini ou hors limites")
        if number != number.quantize(Decimal("0.000001")):
            raise ValueError("Six décimales maximum, sans arrondi automatique")
    except InvalidOperation as exc:
        raise ValueError("Nombre invalide") from exc
    return format(number.normalize(), "f") if number else "0"
