"""Classement explicable des candidats, limité au queryset Sage déjà autorisé."""

from django.db.models import Case, IntegerField, Q, Value, When


def ranked_candidates(rows, inventory, reference):
    """Retourne un queryset paginable classé par preuves, sans élargir son périmètre.

    Aucun seuil de validation n'est modifié. BAP, tiers, libellé, pièce/date et
    montant/signe sont des indices indépendants, jamais une confirmation.
    """
    source = inventory.data
    bap = str(source.get("display_bap") or "").strip()
    if "display_bap" not in source:
        from .presentation import inventory_baps

        bap = inventory_baps([inventory], inventory.campaign)[inventory.pk]
    clues = []
    for lookup, value, weight in (
        ("data__attributes__Référence__iexact", bap, 16),
        (
            "data__entry__third_party__iexact",
            str(source.get("sage_third_party_code") or "").strip(),
            8,
        ),
        ("data__entry__label__iexact", str(source.get("atlas_label") or "").strip(), 4),
        ("document__iexact", str(source.get("sage_document_number") or "").strip(), 2),
        ("data__entry__date", source.get("accounting_date"), 2),
    ):
        if value:
            clues.append((lookup, value, weight))
    score = Value(0, output_field=IntegerField())
    for lookup, value, weight in clues:
        score = score + Case(When(**{lookup: value}, then=Value(weight)), default=Value(0))
    if reference is not None:
        score += Case(When(amount=reference, then=Value(2)), default=Value(0))
        sign = Q(amount__gte=0) if reference >= 0 else Q(amount__lt=0)
        score += Case(When(sign, then=Value(1)), default=Value(0))
    return rows.annotate(relevance=score).order_by("-relevance", "document", "pk")


def candidate_clues(inventory, entry, bap):
    """Décrit les indices de la seule page affichée, sans requête ni assimilation à une preuve."""
    source, target = inventory.data, entry.data["entry"]
    clues = []
    for label, left, right in (
        ("BAP", bap, entry.data.get("attributes", {}).get("Référence")),
        ("Tiers", source.get("sage_third_party_code"), target.get("third_party")),
        ("Libellé", source.get("atlas_label"), target.get("label")),
        ("Pièce", source.get("sage_document_number"), target.get("document")),
        ("Date", source.get("accounting_date"), target.get("date")),
    ):
        if left and right and str(left).strip().casefold() == str(right).strip().casefold():
            clues.append(label)
    return clues
