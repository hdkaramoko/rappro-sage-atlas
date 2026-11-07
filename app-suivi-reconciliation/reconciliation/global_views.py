"""Façade métier des contrôles globaux matérialisés, sans second moteur."""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import BooleanField, Case, Exists, F, Func, IntegerField, OuterRef, Q, Value, When
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from .campaign_views import inventory_for, projects_for
from .journey import filter_menu, safe_return, selections
from .models import Campaign, CampaignGlobalControl, CampaignReview, ControlContribution, ManualAllocation


class HasControlContext(Func):
    """Teste une clé de contexte JSON dynamique en SQL SQLite et PostgreSQL.

    Expressions ORM paramétrées uniquement ; aucune interpolation de saisie SQL.
    Sert à signaler les propositions non confirmées concernant le contrôle affiché.
    """
    output_field = BooleanField()
    arity = 2

    def as_sqlite(self, compiler, connection, **extra_context):
        """Compile le test d'existence SQLite ; les clés sont des empreintes hexadécimales."""
        context, cp = compiler.compile(self.source_expressions[0])
        key, kp = compiler.compile(self.source_expressions[1])
        return f"json_type({context}, '$.' || {key}) IS NOT NULL", [*cp, *kp]

    def as_postgresql(self, compiler, connection, **extra_context):
        """Compile l'opérateur JSONB PostgreSQL, sans conversion en recherche textuelle."""
        context, cp = compiler.compile(self.source_expressions[0])
        key, kp = compiler.compile(self.source_expressions[1])
        return f"({context} ? {key})", [*cp, *kp]


def global_controls_for(user):
    """Retourne les contrôles publiés du portefeuille avec leur résultat courant.

    Le statut stocké n'est pas remplacé par une égalité calculée dans la vue.
    Un contexte Envoyé non confirmé ajoute une alerte distincte en lecture seule.
    Les requêtes corrélées et filtres restent SQL jusqu'à la pagination.
    """
    pending = CampaignReview.objects.filter(campaign_id=OuterRef("campaign_id"),
        project__code=OuterRef("project_code")).exclude(decision__state="VALIDATED", decision__current=True).filter(
            HasControlContext(F("decision__multiple_context__controls"), OuterRef("key")))
    return CampaignGlobalControl.objects.filter(campaign__published=True,
        project_code__in=projects_for(user).values("code")).select_related("campaign").annotate(
            result=Coalesce("current_data", "data"), pending=Exists(pending))


def control_workspace(request):
    """Affiche les anomalies courantes par défaut, avec filtres et pagination serveur.

    Appelé depuis la vue authentifiée Mes rapprochements. EQUILIBRE n'est présenté
    comme réconcilié qu'en l'absence de proposition concernant la pièce encore
    non confirmée. ODS/ODG conserve la clé composite existante. Aucune écriture.
    """
    campaign = Campaign.objects.filter(is_current=True).first()
    rows = global_controls_for(request.user).filter(campaign=campaign)
    projects = list(rows.order_by("project_code").values_list("project_code", flat=True).distinct())
    selected = selections(request.GET, "project", projects)
    states = [("ANOMALY", "Anomalies à examiner"), ("RECONCILED", "Réconciliés"), ("EXCLUDED", "Exclus")]
    chosen = selections(request.GET, "control_state", [key for key, _ in states], ("ANOMALY",))
    reconciled = Q(result__state="EQUILIBRE", pending=False)
    if selected:
        rows = rows.filter(project_code__in=selected)
    if chosen:
        condition = Q(pk__in=[])
        if "ANOMALY" in chosen:
            condition |= Q(result__state__in=["ECART", "INDETERMINE"]) | Q(pending=True)
        if "RECONCILED" in chosen:
            condition |= reconciled
        if "EXCLUDED" in chosen:
            condition |= Q(result__state="EXCLU", pending=False)
        rows = rows.filter(condition)
    search = request.GET.get("q", "").strip()
    if search:
        rows = rows.filter(Q(project_code__icontains=search) | Q(result__identity__parts__2__icontains=search))
    rows = rows.annotate(priority=Case(When(reconciled, then=Value(1)), default=Value(0), output_field=IntegerField()))
    page = Paginator(rows.order_by("priority", "project_code", "pk"), 50).get_page(request.GET.get("page"))
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
    related = CampaignReview.objects.filter(campaign=control.campaign, project__code=control.project_code).filter(
        HasControlContext(F("decision__multiple_context__controls"), Value(control.key))).values("line__transaction__business_key")
    contributions = ControlContribution.objects.filter(control__campaign=control.campaign,
        control__key=control.key).values("line__transaction__business_key")
    rows = inventory_for(request.user).filter(campaign=control.campaign, present=True).filter(
        Q(control_key=control.key) | Q(pk__in=assigned) | Q(business_key__in=related) | Q(business_key__in=contributions)).order_by("source_id", "pk")
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    return render(request, "reconciliation/global_control_detail.html", {"control": control, "page": page,
        "legacy": control.campaign.controls.filter(key=control.key).first(),
        "return_url": safe_return(request.GET.get("return", "")),
        "page_range": page.paginator.get_elided_page_range(page.number)})
