"""Façade métier des contrôles globaux matérialisés, sans second moteur."""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, CharField, F, Q, Value, When
from django.db.models.functions import Coalesce, NullIf, Substr, Upper
from django.db.models.fields.json import KeyTextTransform
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


def with_piece_type(rows):
    """Annote le type des contrôles autorisés, sans recalcul ni écriture.

    Réutilise la projection de cadrage si disponible ; le JSON est le repli des
    anciens contrôles. Les groupes composites conservent le libellé ODS/ODG.
    """
    fallback = Case(When(result__identity__strategy="ODS_ODG_BY_GROUP", then=Value("ODS/ODG")),
        default=Coalesce(NullIf(Upper(Substr(KeyTextTransform.from_lookup("result__identity__parts__2"), 1, 3)), Value("")), Value("NA")),
        output_field=CharField())
    return rows.annotate(filter_piece_type=Case(
        When(accounting__piece_type__in=["ODS", "ODG", "ODS/ODG", "MIXTE"], then=Value("ODS/ODG")),
        default=Coalesce(F("accounting__piece_type"), fallback), output_field=CharField()))


def control_workspace(request):
    """Affiche les anomalies courantes par défaut, avec filtres et pagination serveur.

    Appelé depuis la vue authentifiée Mes rapprochements. Les choix GET multiples
    filtrent current_state ; Toutes retire cette restriction. Les anciennes URL
    ANOMALY/RECONCILED/EXCLUDED restent acceptées avec leur sens historique.
    Une proposition non confirmée reste une alerte distincte de l'état courant.
    ODS/ODG conserve la clé composite existante. Retour HTML, aucune écriture.
    Pagination sur les seuls identifiants avant chargement des JSON et tri stable
    sur projet/identifiant, sans calcul de priorité ni N+1.
    Origine utilise en SQL les compteurs de sources et confirmations du résultat
    courant, jamais les montants. Sans inventaire Sage complet, l'origine reste
    inconnue ; Toutes conserve ces groupes ainsi que les sources exclues.
    Origine et Type de pièce valent Toutes par défaut. Le type filtre côté
    serveur avant pagination, sans modifier les calculs ni étendre les droits.
    """
    campaign = Campaign.objects.filter(is_current=True).first()
    rows = global_controls_for(request.user).filter(campaign=campaign)
    projects = list(rows.order_by("project_code").values_list("project_code", flat=True).distinct())
    kinds = list(with_piece_type(rows).order_by("filter_piece_type").values_list("filter_piece_type", flat=True).distinct())
    chosen_types = selections(request.GET, "piece_type", kinds)
    if chosen_types:
        rows = with_piece_type(rows).filter(filter_piece_type__in=chosen_types)
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
    origins = [("atlas", "Atlas uniquement"), ("sage", "Sage uniquement"), ("both", "Présentes dans les deux")]
    origin = selections(request.GET, "origin", [key for key, _ in origins])
    if origin:
        from reconciliation_contract.sage_inventory import CAPABILITY
        if campaign is None or CAPABILITY not in campaign.metadata.get("capabilities", []):
            rows = rows.none()
        else:
            atlas_present = Q(result__atlas_count__gt=0) | Q(result__confirmed_allocations__0__isnull=False)
            sage_present = Q(result__sage_count__gt=0) & ~Q(current_state="EXCLU")
            # Des compteurs absents ne prouvent jamais l'absence d'une source.
            rows = rows.exclude(current_state="EXCLU").filter(
                result__atlas_count__isnull=False, result__sage_count__isnull=False).exclude(
                Q(result__atlas_count=None) | Q(result__sage_count=None))
            condition = Q(pk__in=[])
            if "atlas" in origin:
                condition |= atlas_present & ~sage_present
            if "sage" in origin:
                condition |= sage_present & ~atlas_present
            if "both" in origin:
                condition |= atlas_present & sage_present
            rows = rows.filter(condition)
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
                         filter_menu("control_state", "État du contrôle", states, chosen),
                         filter_menu("piece_type", "Type de pièce", [(kind, "Type inconnu" if kind == "NA" else kind) for kind in kinds], chosen_types),
                         filter_menu("origin", "Origine", origins, origin)],
        "page_range": page.paginator.get_elided_page_range(page.number)})


@login_required
@require_GET
def global_control_detail(request, pk):
    """Présente les montants courant/initial et les sources autorisées du contrôle pk.

    Inventaire Atlas paginé, incluant les sources affectées manuellement à la clé.
    Les actions restent déléguées aux fiches existantes et services Lot 2. Une
    campagne historique est consultable sans toucher ses décisions. Retour HTML,
    404 hors portefeuille ; aucun calcul ou mutation lors de la consultation.
    Les deux tableaux sont paginés indépendamment. Les écritures Sage viennent
    de la clé du contrôle (ou de ses preuves historiques), jamais d'un montant.
    BAP et libellés sont des données de présentation ; aucun état n'est recalculé.
    Le diagnostic ODA préparé est joint en lecture seule, sans ajouter de décision.
    """
    control = get_object_or_404(global_controls_for(request.user).select_related("accounting"), pk=pk)
    assigned = ManualAllocation.objects.filter(entry__campaign=control.campaign, entry__control_key=control.key,
        active=True, link__active=True).values("link__inventory_id")
    related = ReviewControlContext.objects.filter(campaign=control.campaign, project_code=control.project_code,
        key=control.key).values("review__line__transaction__business_key")
    contributions = ControlContribution.objects.filter(control__campaign=control.campaign,
        control__key=control.key).values("line__transaction__business_key")
    rows = inventory_for(request.user).filter(campaign=control.campaign, present=True).filter(
        Q(control_key=control.key) | Q(pk__in=assigned) | Q(business_key__in=related) | Q(business_key__in=contributions)).order_by("source_id", "pk")
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    from .presentation import inventory_baps
    atlas_rows = list(page.object_list)
    baps = inventory_baps(atlas_rows, control.campaign)
    for row in atlas_rows:
        row.atlas_bap = baps[row.pk]
    page.object_list = atlas_rows
    legacy = control.campaign.controls.filter(key=control.key).first()
    from reconciliation_contract.sage_inventory import CAPABILITY
    if CAPABILITY in control.campaign.metadata.get("capabilities", []):
        sources = control.campaign.sage_inventory.filter(control_key=control.key,
            project_code=control.project_code).order_by("pk")
        sage_page = Paginator(sources, 25).get_page(request.GET.get("sage_page"))
        sage_page.object_list = [{**row.data["entry"], "bap": row.data.get("attributes", {}).get("Référence", "")}
                                for row in sage_page.object_list]
    else:
        sage_page = Paginator(legacy.data.get("entries", []) if legacy else [], 25).get_page(request.GET.get("sage_page"))
    return render(request, "reconciliation/global_control_detail.html", {"control": control, "page": page,
        "legacy": legacy, "sage_page": sage_page,
        "sage_page_range": sage_page.paginator.get_elided_page_range(sage_page.number),
        "return_url": safe_return(request.GET.get("return", "")),
        "page_range": page.paginator.get_elided_page_range(page.number)})
