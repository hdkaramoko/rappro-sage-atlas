"""Parcours projet → lignes Comptabilisé incomplètes, indépendant des groupes financiers."""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, DecimalField, F, IntegerField, Q, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, NullIf
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .campaign_views import inventory_for, projects_for
from .departments import department_filter, pole_filter
from .incomplete_accounting import comparison_amount, current_manual_link, missing_labels
from .journey import filter_menu, safe_return, selections
from .models import Campaign
from .presentation import inventory_baps

STATES = [("active", "À traiter"), ("resolved", "Résolus")]


def incomplete_rows(user, campaign):
    """Retourne les sources autorisées avec un prédicat SQL de confirmation courante.

    Le masque source reste intact. Le diagnostic V1 est non nul uniquement pour
    le statut source Comptabilisé, immuable : il sélectionne ces lignes sans scan
    JSON de statut sur tout le périmètre. Le prédicat reproduit current_manual_link :
    lien actif, version de correction, absence d'exclusion et montant de référence
    identique. Les sources importées sont des montants canoniques ; le bit montant
    invalide empêche de convertir ce montant Sage en faux zéro. Aucun candidat,
    écriture, recalcul ni lecture de tous les JSON en Python n'est effectué.
    """
    rows = inventory_for(user).filter(campaign=campaign, present=True, sage_missing_mask__gt=0)
    decimal = DecimalField(max_digits=28, decimal_places=9)

    def amount(field):
        """Extrait un scalaire JSON canonique, avec NULL explicite pour une absence."""
        return Cast(
            NullIf(NullIf(KeyTextTransform(field, "data"), Value("null")), Value("")), decimal
        )

    rows = rows.alias(_missing_amount=F("sage_missing_mask").bitand(1))
    project_amount = amount("total_project_charges")
    if campaign and campaign.metadata.get("amount_field") == "total_project_charges":
        source_reference = project_amount
    else:
        source_reference = Case(
            When(_missing_amount=1, then=project_amount),
            default=amount("total_sage_charges"),
            output_field=decimal,
        )
    reference = Case(
        When(adjustment__active=True, then=F("adjustment__amount")),
        default=source_reference,
        output_field=decimal,
    )
    version = Coalesce(F("adjustment__version"), Value(0), output_field=IntegerField())
    current = Q(inventory_match__active=True, inventory_match__adjustment_version=version)
    current &= ~Q(adjustment__active=True, adjustment__reason="DUPLICATE")
    # La lecture du montant JSON n'est nécessaire que pour un lien/version courant.
    resolved = Case(
        When(
            current,
            then=Case(
                When(inventory_match__amount=reference, then=Value(True)), default=Value(False)
            ),
        ),
        default=Value(False),
    )
    return rows.alias(_incomplete_resolved=resolved)


def state_scope(rows, request):
    """Applique À traiter/Résolus/Toutes en SQL et retourne le menu, sans effet de bord."""
    chosen = selections(request.GET, "resolution", [key for key, _ in STATES], ("active",))
    if chosen == ["active"]:
        rows = rows.filter(_incomplete_resolved=False)
    elif chosen == ["resolved"]:
        rows = rows.filter(_incomplete_resolved=True)
    return rows, filter_menu("resolution", "Traitement", STATES, chosen)


@login_required
@require_GET
def project_list(request):
    """Affiche une ligne par projet autorisé, avec effectif distinct et pagination SQL.

    Tous les filtres précèdent l'agrégation. Les relations utilisées sont uniques
    par ligne, sans jointure aux contrôles/allocations. Aucun candidat n'est chargé.
    Les projets entièrement résolus quittent la file active, restent dans Résolus.
    """
    campaign = Campaign.objects.filter(is_current=True).first()
    rows = incomplete_rows(request.user, campaign)
    codes = list(rows.order_by("project_code").values_list("project_code", flat=True).distinct())
    organization_scope = rows
    rows, department_menu = department_filter(rows, campaign, request, has_projects=bool(codes))
    rows, pole_menu = pole_filter(
        rows, campaign, request, has_projects=bool(codes), scope=organization_scope
    )
    selected = selections(request.GET, "project", codes)
    if selected:
        rows = rows.filter(project_code__in=selected)
    search = request.GET.get("q", "").strip()
    if search:
        labels = projects_for(request.user).filter(label__icontains=search).values("code")
        rows = rows.filter(Q(project_code__icontains=search) | Q(project_code__in=labels))
    rows, state_menu = state_scope(rows, request)
    grouped = (
        rows.order_by()
        .values("project_code")
        .annotate(line_count=Count("pk", distinct=True))
        .order_by("project_code")
    )
    page = Paginator(grouped, 40).get_page(request.GET.get("page"))
    items = list(page.object_list)
    labels = (
        projects_for(request.user)
        .filter(code__in=[item["project_code"] for item in items])
        .in_bulk(field_name="code")
    )
    # Comme la liste financière, tolère un retrait de portefeuille concurrent.
    items = [item for item in items if item["project_code"] in labels]
    for item in items:
        item["label"] = labels[item["project_code"]].label
    page.object_list = items
    return render(
        request,
        "reconciliation/incomplete_projects.html",
        {
            "active_view": "controls",
            "control_channel": "incomplete",
            "campaign": campaign,
            "page": page,
            "search": search,
            "resolution_values": state_menu["selected"] or [""],
            "count_label": "Nombre de lignes à traiter"
            if state_menu["selected"] == ["active"]
            else "Nombre de lignes résolues"
            if state_menu["selected"] == ["resolved"]
            else "Nombre de lignes",
            "filter_menus": [
                filter_menu("project", "Projet", [(code, code) for code in codes], selected),
                department_menu,
                pole_menu,
                state_menu,
            ],
            "page_range": page.paginator.get_elided_page_range(page.number),
        },
    )


@login_required
@require_GET
def project_detail(request, project_code):
    """Affiche uniquement les Comptabilisé incomplets du projet autorisé et de la page.

    Retourne 404 hors portefeuille, 405 pour POST. Campagne courante implicite ;
    aucune mutation ni modification du cadrage. Les confirmations restent sur la
    fiche V1. Le retour y conserve filtres, pagination et ancre du tableau projet.
    """
    project = get_object_or_404(projects_for(request.user), code=project_code)
    campaign = Campaign.objects.filter(is_current=True).first()
    rows = incomplete_rows(request.user, campaign).filter(project_code=project.code)
    rows, state_menu = state_scope(rows, request)
    search = request.GET.get("q", "").strip()
    if search:
        rows = rows.filter(
            Q(source_id__icontains=search)
            | Q(data__display_bap__icontains=search)
            | Q(data__sage_third_party_code__icontains=search)
            | Q(data__atlas_label__icontains=search)
        )
    page = Paginator(
        rows.select_related("campaign", "adjustment", "inventory_match").order_by(
            "source_id", "pk"
        ),
        25,
    ).get_page(request.GET.get("page"))
    items = list(page.object_list)
    baps = inventory_baps(items, campaign) if campaign else {}
    focus = request.GET.get("focus", "")
    focus = int(focus) if len(focus) < 20 and focus.isdecimal() else None
    visible_ids = {row.pk for row in items}
    for row in items:
        row.atlas_bap = baps[row.pk]
        row.sage_missing_labels = missing_labels(row)
        row.review_reference = comparison_amount(row)
        adjustment = getattr(row, "adjustment", None)
        row.reference_origin = (
            "Montant métier corrigé"
            if adjustment and adjustment.active
            else "Charges projet (référence)"
            if row.sage_missing_mask & 1
            or campaign.metadata.get("amount_field") == "total_project_charges"
            else "Charges Sage Atlas"
        )
        row.resolved_link = current_manual_link(row)
        context = request.GET.copy()
        context["focus"] = str(row.pk)
        row.review_return = request.path + "?" + context.urlencode() + f"#incomplete-line-{row.pk}"
    page.object_list = items
    return render(
        request,
        "reconciliation/incomplete_project.html",
        {
            "active_view": "controls",
            "control_channel": "incomplete",
            "campaign": campaign,
            "project": project,
            "page": page,
            "search": search,
            "filter_menus": [state_menu],
            "return_url": safe_return(
                request.GET.get("return", ""),
                reverse("reconciliation:reviews") + "?view=controls&channel=incomplete",
            ),
            "missing_focus": focus if focus not in visible_ids else None,
            "page_range": page.paginator.get_elided_page_range(page.number),
        },
    )
