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
    return organization_filter(rows, campaign, request, code_field, has_projects=has_projects,
        field="consolidated", parameter="department", label="Département", policy="department_policy",
        fallback="", fallback_option=MISSING, fallback_label="Non renseigné")


def pole_filter(rows, campaign, request, code_field="project_code", *, has_projects=None, scope=None):
    """Filtre les pôles photographiés, avec Hors DP pour toute absence historique.

    Réutilise le mécanisme Département ; scope conserve les options du périmètre
    autorisé avant combinaison des filtres. Retourne (queryset, menu Pôle),
    sans modifier sources, décisions ou droits ; aucune requête par ligne.
    """
    return organization_filter(rows, campaign, request, code_field, has_projects=has_projects,
        field="pole", parameter="pole", label="Pôle", policy="pole_policy", fallback="Hors DP",
        fallback_option="Hors DP", fallback_label="Hors DP", scope=scope)


def organization_filter(rows, campaign, request, code_field, *, has_projects, field, parameter,
                        label, policy, fallback, fallback_option, fallback_label, scope=None):
    """Applique une dimension organisationnelle interne à un queryset déjà autorisé.

    Les arguments de champ sont fixés par les deux façades, jamais par GET.
    Retourne le queryset et son menu ; options distinctes SQL, absence explicite,
    union des choix puis intersection avec les autres filtres. Aucun effet métier.
    """
    scope = rows if scope is None else scope
    if campaign is None or not campaign.metadata.get(policy):
        available = rows.exists() if has_projects is None else has_projects
        options = [(fallback_option, fallback_label)] if available else []
        selected = selections(request.GET, parameter, [v for v, _ in options])
        return rows, filter_menu(parameter, label, options, selected)
    associations = CampaignDepartment.objects.filter(campaign=campaign)
    codes = scope.order_by().values(code_field)
    choices = list(associations.filter(project_code__in=codes).exclude(**{field: fallback}).order_by(
        field).values_list(field, flat=True).distinct())
    known = associations.exclude(**{field: fallback}).values("project_code")
    missing = scope.exclude(**{f"{code_field}__in": known}).exists()
    options = [(value, value) for value in choices]
    if missing:
        options.append((fallback_option, fallback_label))
    selected = selections(request.GET, parameter, [value for value, _ in options])
    if selected:
        matching = associations.filter(**{f"{field}__in": [v for v in selected if v != fallback_option]}).values("project_code")
        condition = Q(**{f"{code_field}__in": matching})
        if fallback_option in selected:
            condition |= ~Q(**{f"{code_field}__in": known})
        rows = rows.filter(condition)
    return rows, filter_menu(parameter, label, options, selected)
