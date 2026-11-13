"""Filtres départementaux historisés, appliqués après restriction du portefeuille."""

from django.db.models import Q

from .journey import filter_menu, selections
from .models import CampaignDepartment

MISSING = "__NO_DEPARTMENT__"


def department_filter(rows, campaign, request, code_field="project_code", *, has_projects=None):
    """Retourne (queryset filtré, menu Département) pour un périmètre déjà autorisé.

    Les options viennent uniquement des projets visibles de la campagne. Les
    valeurs sont transcodifiées ; absence de ligne historique ou valeur vide
    signifie Non renseigné. Multisélection avant pagination, sans écritures ni
    changement de droits. Quelques requêtes bornées, aucune lecture par ligne.
    has_projects réutilise la liste de projets déjà chargée par la vue pour
    éviter toute requête supplémentaire sur les campagnes non enrichies.
    """
    if campaign is None or not campaign.metadata.get("department_policy"):
        available = rows.exists() if has_projects is None else has_projects
        options = [(MISSING, "Non renseigné")] if available else []
        selected = selections(request.GET, "department", [v for v, _ in options])
        return rows, filter_menu("department", "Département", options, selected)
    associations = CampaignDepartment.objects.filter(campaign=campaign)
    codes = rows.order_by().values(code_field)
    choices = list(associations.filter(project_code__in=codes).exclude(consolidated="").order_by(
        "consolidated").values_list("consolidated", flat=True).distinct())
    known = associations.exclude(consolidated="").values("project_code")
    missing = rows.exclude(**{f"{code_field}__in": known}).exists()
    options = [(value, value) for value in choices]
    if missing:
        options.append((MISSING, "Non renseigné"))
    selected = selections(request.GET, "department", [value for value, _ in options])
    if selected:
        matching = associations.filter(consolidated__in=[v for v in selected if v != MISSING]).values("project_code")
        condition = Q(**{f"{code_field}__in": matching})
        if MISSING in selected:
            condition |= ~Q(**{f"{code_field}__in": known})
        rows = rows.filter(condition)
    return rows, filter_menu("department", "Département", options, selected)
