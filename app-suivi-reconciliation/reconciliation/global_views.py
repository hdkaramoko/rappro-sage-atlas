"""Façade métier des contrôles globaux matérialisés, sans second moteur."""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from .campaign_views import inventory_for, projects_for
from .journey import filter_menu, safe_return, selections
from .models import Campaign, CampaignGlobalControl, ControlContribution, ManualAllocation, ReviewControlContext


def global_controls_for(user):
    """Retourne les contrôles publiés du portefeuille avec leur résultat courant.

    Le statut stocké n'est pas remplacé par une égalité calculée dans la vue.
    Les colonnes techniques current_state/has_pending sont actualisées lors des
    écritures métier. Les filtres d'état n'explorent aucun JSON ni sous-requête
    corrélée. Une recherche textuelle explicite peut encore filtrer l'identité JSON.
    Le JSON courant n'est chargé que pour la page demandée ou la fiche précise.
    """
    return CampaignGlobalControl.objects.filter(campaign__published=True,
        project_code__in=projects_for(user).values("code")).select_related("campaign").annotate(
            result=Coalesce("current_data", "data"), pending=F("has_pending"))


def control_workspace(request):
    """Affiche les anomalies courantes par défaut, avec filtres et pagination serveur.

    Appelé depuis la vue authentifiée Mes rapprochements. Les choix GET multiples
    filtrent current_state ; Toutes retire cette restriction. Les anciennes URL
    ANOMALY/RECONCILED/EXCLUDED restent acceptées avec leur sens historique.
    Une proposition non confirmée reste une alerte distincte de l'état courant.
    ODS/ODG conserve la clé composite existante. Retour HTML, aucune écriture.
    Pagination sur les seuls identifiants avant chargement des JSON et tri stable
    sur projet/identifiant, sans calcul de priorité ni N+1.
    """
    campaign = Campaign.objects.filter(is_current=True).first()
    rows = global_controls_for(request.user).filter(campaign=campaign)
    projects = list(rows.order_by("project_code").values_list("project_code", flat=True).distinct())
    selected = selections(request.GET, "project", projects)
    states = [("EQUILIBRE", "Équilibré"), ("ECART", "Écart"), ("INDETERMINE", "À revoir"), ("EXCLU", "Exclu")]
    legacy = {"ANOMALY": ["ECART", "INDETERMINE"], "RECONCILED": ["EQUILIBRE"], "EXCLUDED": ["EXCLU"]}
    chosen = selections(request.GET, "control_state", [key for key, _ in states] + list(legacy), ("ECART", "INDETERMINE"))
    if selected:
        rows = rows.filter(project_code__in=selected)
    if chosen:
        condition = Q(current_state__in=[value for value in chosen if value not in legacy])
        if "ANOMALY" in chosen:
            condition |= Q(current_state__in=["ECART", "INDETERMINE"]) | Q(has_pending=True)
        if "RECONCILED" in chosen:
            condition |= Q(current_state="EQUILIBRE", has_pending=False)
        if "EXCLUDED" in chosen:
            condition |= Q(current_state="EXCLU", has_pending=False)
        rows = rows.filter(condition)
    chosen = list(dict.fromkeys(state for value in chosen for state in legacy.get(value, [value])))
    search = request.GET.get("q", "").strip()
    if search:
        rows = rows.filter(Q(project_code__icontains=search) | Q(result__identity__parts__2__icontains=search))
    rows = rows.order_by("project_code", "pk")
    page = Paginator(rows.values_list("pk", flat=True), 50).get_page(request.GET.get("page"))
    identifiers = list(page.object_list)
    controls = {row.pk: row for row in global_controls_for(request.user).filter(pk__in=identifiers)}
    page.object_list = [controls[pk] for pk in identifiers if pk in controls]
    return render(request, "reconciliation/global_controls.html", {"active_view": "controls", "campaign": campaign,
        "page": page, "search": search,
        "filter_menus": [filter_menu("project", "Projet", [(p, p) for p in projects], selected),
                         filter_menu("control_state", "État du contrôle", states, chosen)],
        "page_range": page.paginator.get_elided_page_range(page.number)})


@login_required
@require_GET
def global_control_detail(request, pk):
    """Présente les montants courant/initial et les sources autorisées du contrôle pk.

    Inventaire Atlas paginé, incluant les sources affectées manuellement à la clé.
    Les actions restent déléguées aux fiches existantes et services Lot 2. Une
    campagne historique est consultable sans toucher ses décisions. Retour HTML,
    404 hors portefeuille ; aucun calcul ou mutation lors de la consultation.
    """
    control = get_object_or_404(global_controls_for(request.user), pk=pk)
    assigned = ManualAllocation.objects.filter(entry__campaign=control.campaign, entry__control_key=control.key,
        active=True, link__active=True).values("link__inventory_id")
    related = ReviewControlContext.objects.filter(campaign=control.campaign, project_code=control.project_code,
        key=control.key).values("review__line__transaction__business_key")
    contributions = ControlContribution.objects.filter(control__campaign=control.campaign,
        control__key=control.key).values("line__transaction__business_key")
    rows = inventory_for(request.user).filter(campaign=control.campaign, present=True).filter(
        Q(control_key=control.key) | Q(pk__in=assigned) | Q(business_key__in=related) | Q(business_key__in=contributions)).order_by("source_id", "pk")
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    return render(request, "reconciliation/global_control_detail.html", {"control": control, "page": page,
        "legacy": control.campaign.controls.filter(key=control.key).first(),
        "return_url": safe_return(request.GET.get("return", "")),
        "page_range": page.paginator.get_elided_page_range(page.number)})
