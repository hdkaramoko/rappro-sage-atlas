"""Consultation paginée du cadrage, systématiquement limitée au portefeuille."""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Sum, Value, When
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .accounting import STATES
from .accounting_models import AccountingGroup, AccountingProject
from .campaign_views import projects_for
from .journey import filter_menu, safe_return, selections
from .models import Campaign, CampaignInventory, CampaignSageEntry
from reconciliation_contract import money

TABLE_FILTERS = [("all", "Toutes"), ("gap", "Avec écart"), ("balanced", "Équilibrées")]


def selected_campaign(request):
    """Retourne (campagne, message) pour la dernière photographie publiée prête et accessible.

    request fournit le portefeuille ; l'ancien paramètre campaign est ignoré.
    La disponibilité est contrôlée sur les codes source autorisés par deux tests
    SQL d'absence de synthèse préparée, sans charger inventaires ni agrégats.
    Aucun calcul, écriture ou nouveau marqueur de disponibilité n'est introduit.
    Les métadonnées de la campagne sont préchargées pour le filtre Département.
    """
    published = Campaign.objects.order_by("-created_at", "-pk")
    if not published.exists():
        return None, "Aucune campagne publiée disponible."
    allowed = projects_for(request.user).values("code")
    accessible = published.filter(
        Exists(AccountingProject.objects.filter(campaign_id=OuterRef("pk"), project_code__in=allowed)) |
        Exists(CampaignInventory.objects.filter(campaign_id=OuterRef("pk"), project_code__in=allowed, present=True)) |
        Exists(CampaignSageEntry.objects.filter(campaign_id=OuterRef("pk"), project_code__in=allowed)))
    seen = False
    for campaign in accessible.only("id", "name", "fiscal_year", "created_at", "is_current", "metadata").iterator(chunk_size=20):
        seen = True
        ready = AccountingProject.objects.filter(campaign=campaign, project_code__in=allowed, data__prepared=True)
        if not ready.exists():
            continue
        codes = ready.values("project_code")
        missing_atlas = campaign.inventory.filter(present=True, project_code__in=allowed).exclude(project_code__in=codes).exists()
        missing_sage = campaign.sage_inventory.filter(project_code__in=allowed).exclude(project_code__in=codes).exists()
        if not missing_atlas and not missing_sage:
            return campaign, ""
    return None, "Le cadrage des campagnes accessibles n'est pas encore préparé." if seen else "Aucune campagne accessible dans votre portefeuille."


def state_filter(request, name):
    """Lit un choix exclusif GET autorisé ; une valeur absente/inconnue signifie Toutes, sans effet de bord."""
    value = request.GET.get(name, "all")
    return value if value in {key for key, _ in TABLE_FILTERS} else "all"


def filter_parameters(request, excluded):
    """Retourne les champs GET cachés à préserver, y compris valeurs répétées ; aucune mutation de l'URL."""
    return [(key, value) for key, values in request.GET.lists() if key not in excluded for value in values]


@login_required
@require_GET
def accounting_list(request):
    """Affiche les synthèses autorisées avec GET multisélection et pagination, sans calcul métier.

    Les agrégats préparés sont lus en SQL ; une campagne non préparée rend un
    message explicite, jamais de faux zéros. Aucun inventaire chargé par page.
    La campagne est implicite ; les URL historiques ne changent pas la sélection.
    Département utilise le rattachement transcodifié historisé, dans le même
    périmètre autorisé ; tableaux et compteurs partagent ce filtre SQL.
    Le filtre Pôle partage le mécanisme et conserve Hors DP pour l'historique.
    Les quatre sommes de consultation portent sur ce même périmètre après tous
    les filtres et avant pagination ; une absence empêche un faux total complet.
    Leur effectif est réutilisé par le paginateur, sans seconde requête COUNT.
    """
    campaign, availability = selected_campaign(request)
    rows = AccountingProject.objects.filter(campaign=campaign,
        project_code__in=projects_for(request.user).values("code"), data__prepared=True)
    projects = list(rows.order_by("project_code").values_list("project_code", flat=True))
    from .departments import department_filter, pole_filter
    organization_scope = rows
    rows, department_menu = department_filter(rows, campaign, request, has_projects=bool(projects))
    rows, pole_menu = pole_filter(rows, campaign, request, has_projects=bool(projects), scope=organization_scope)
    selected = selections(request.GET, "project", projects)
    states = selections(request.GET, "state", [key for key, _ in STATES])
    search = request.GET.get("q", "").strip()
    if selected:
        rows = rows.filter(project_code__in=selected)
    if states:
        rows = rows.filter(state__in=states)
    if search:
        rows = rows.filter(Q(project_code__icontains=search) | Q(project_code__in=projects_for(request.user).filter(label__icontains=search).values("code")))
    statistics = list(rows.values("state").annotate(count=Count("pk"), gap=Sum("gap")).order_by("state"))
    from .accounting_totals import filtered_totals
    totals = filtered_totals(rows)
    rows = rows.annotate(priority=Case(When(state="NON_CADRE", then=Value(0)), When(state="INSUFFISANT", then=Value(1)),
        default=Value(2), output_field=IntegerField())).order_by("priority", "project_code", "pk")
    paginator = Paginator(rows, 40)
    paginator.count = totals["count"]
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "reconciliation/accounting_list.html", {"campaign": campaign,
        "availability": availability, "legacy_campaign": "campaign" in request.GET,
        "page": page, "search": search, "statistics": statistics, "totals": totals,
        "filter_menus": [filter_menu("project", "Projet", [(p, p) for p in projects], selected),
                         department_menu,
                         pole_menu,
                         filter_menu("state", "État du cadrage", STATES, states)],
        "page_range": page.paginator.get_elided_page_range(page.number)})


@login_required
@require_GET
def accounting_detail(request, pk):
    """Présente un projet autorisé, ses types et groupes paginés ; 404 hors portefeuille.

    Le résultat enregistré est consultatif. Les liens descendants portent un
    retour local contrôlé ; les décisions restent dans les fiches existantes.
    Les filtres type_state et group_state restent indépendants. L'écart stocké
    est comparé à zéro sans arrondi/tolérance supplémentaire. Les groupes exclus
    ou insuffisants ne sont jamais qualifiés d'équilibrés. Les Sage sans Atlas
    restent comparables après reconstruction du périmètre exhaustif.
    """
    summary = get_object_or_404(AccountingProject.objects.select_related("campaign").filter(campaign__published=True,
        project_code__in=projects_for(request.user).values("code")), pk=pk)
    type_state, group_state = state_filter(request, "type_state"), state_filter(request, "group_state")
    types = summary.data.get("types", [])
    kinds = [row["type"] for row in types]
    kind = request.GET.get("type", "")
    rows = AccountingGroup.objects.filter(campaign=summary.campaign, project_code=summary.project_code)
    in_scope = Q(data__excluded=False)
    if summary.data.get("accounting_policy") != "exhaustive-sage-v1":
        in_scope &= Q(data__attached=True)
    type_statuses = {row["piece_type"]: row for row in rows.values("piece_type").annotate(
        attached=Count("pk", filter=in_scope), insufficient=Count("pk", filter=in_scope & Q(state="INSUFFISANT")))}
    shown_types = []
    for row in types:
        status = type_statuses.get(row["type"], {})
        gap = money(row.get("gap"))
        comparable = gap is not None and row.get("atlas") is not None and row.get("sage") is not None and status.get("attached", 0) > 0 and not status.get("insufficient", 0)
        if type_state == "all" or comparable and ((type_state == "balanced" and gap == 0) or (type_state == "gap" and gap != 0)):
            shown_types.append(row)
    if kind:
        rows = rows.filter(piece_type=kind) if kind in kinds else rows.none()
    if group_state != "all":
        rows = rows.filter(in_scope, atlas__isnull=False, sage__isnull=False, gap__isnull=False)
        rows = rows.filter(state="CADRE", gap=0) if group_state == "balanced" else rows.filter(state="NON_CADRE").exclude(gap=0)
    page = Paginator(rows.order_by("piece_type", "pk"), 25).get_page(request.GET.get("page"))
    return render(request, "reconciliation/accounting_detail.html", {"summary": summary, "page": page,
        "kind": kind, "type_rows": shown_types, "type_total": len(types), "type_state": type_state,
        "group_state": group_state, "table_filter_choices": TABLE_FILTERS,
        "type_parameters": filter_parameters(request, {"type_state"}),
        "group_parameters": filter_parameters(request, {"group_state", "page"}),
        "return_url": safe_return(request.GET.get("return", ""), reverse("reconciliation:accounting-list")),
        "page_range": page.paginator.get_elided_page_range(page.number)})
