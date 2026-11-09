"""Consultation paginée du cadrage, systématiquement limitée au portefeuille."""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Q, Sum, Value, When
from django.shortcuts import get_object_or_404, render
from django.http import Http404
from django.urls import reverse
from django.views.decorators.http import require_GET

from .accounting import STATES
from .accounting_models import AccountingGroup, AccountingProject
from .campaign_views import projects_for
from .journey import filter_menu, safe_return, selections
from .models import Campaign


def selected_campaign(request):
    """Lit la campagne publiée demandée ou courante ; retourne None si aucune, 404 si ID interdit."""
    if request.GET.get("campaign"):
        if not request.GET["campaign"].isascii() or not request.GET["campaign"].isdecimal():
            raise Http404("Campagne inconnue")
        return get_object_or_404(Campaign.objects.all(), pk=request.GET["campaign"])
    return Campaign.objects.filter(is_current=True).first()


@login_required
@require_GET
def accounting_list(request):
    """Affiche les synthèses autorisées avec GET multisélection et pagination, sans calcul métier.

    Les agrégats préparés sont lus en SQL ; une campagne non préparée rend un
    message explicite, jamais de faux zéros. Aucun inventaire chargé par page.
    """
    campaign = selected_campaign(request)
    rows = AccountingProject.objects.filter(campaign=campaign,
        project_code__in=projects_for(request.user).values("code"))
    projects = list(rows.order_by("project_code").values_list("project_code", flat=True))
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
    rows = rows.annotate(priority=Case(When(state="NON_CADRE", then=Value(0)), When(state="INSUFFISANT", then=Value(1)),
        default=Value(2), output_field=IntegerField())).order_by("priority", "project_code", "pk")
    page = Paginator(rows, 40).get_page(request.GET.get("page"))
    return render(request, "reconciliation/accounting_list.html", {"campaign": campaign,
        "campaigns": Campaign.objects.order_by("-pk"), "page": page, "search": search, "statistics": statistics,
        "filter_menus": [filter_menu("project", "Projet", [(p, p) for p in projects], selected),
                         filter_menu("state", "État du cadrage", STATES, states)],
        "page_range": page.paginator.get_elided_page_range(page.number)})


@login_required
@require_GET
def accounting_detail(request, pk):
    """Présente un projet autorisé, ses types et groupes paginés ; 404 hors portefeuille.

    Le résultat enregistré est consultatif. Les liens descendants portent un
    retour local contrôlé ; les décisions restent dans les fiches existantes.
    """
    summary = get_object_or_404(AccountingProject.objects.select_related("campaign").filter(campaign__published=True,
        project_code__in=projects_for(request.user).values("code")), pk=pk)
    kinds = [row["type"] for row in summary.data.get("types", [])]
    kind = request.GET.get("type", "")
    rows = AccountingGroup.objects.filter(campaign=summary.campaign, project_code=summary.project_code)
    if kind:
        rows = rows.filter(piece_type=kind) if kind in kinds else rows.none()
    page = Paginator(rows.order_by("piece_type", "pk"), 25).get_page(request.GET.get("page"))
    return render(request, "reconciliation/accounting_detail.html", {"summary": summary, "page": page,
        "kind": kind, "return_url": safe_return(request.GET.get("return", ""), reverse("reconciliation:accounting-list")),
        "page_range": page.paginator.get_elided_page_range(page.number)})
