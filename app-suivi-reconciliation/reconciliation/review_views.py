"""Écrans de décision par ligne et fichier de conservation des validations."""

from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Sum, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from .models import Campaign, CampaignInventory, CampaignReview, LineReview, ReconciliationTransaction
from .presentation import decorate, history_rows, rule_choices
from .review import decide, effective, is_current, signature
from .review_forms import LineReviewForm
from .journey import filter_menu, line_actions, no_match_query, safe_return, selections


def visible(user):
    """Retourne les lignes autorisées de la campagne publiée courante, ou héritées.

    Exclut toujours les campagnes cachées et précharge les relations de fraîcheur
    pour éviter les requêtes par ligne. Aucun écrit ; droits portefeuille appliqués
    par visible_for, même pour un identifiant ou filtre fourni manuellement.
    """
    items = LineReview.objects.filter(Q(campaign__isnull=True) | Q(campaign__published=True)).filter(
        transaction__in=ReconciliationTransaction.objects.visible_for(user)
    ).select_related(
        "transaction",
        "transaction__project",
        "group",
        "campaign",
        "validation_origin",
        "updated_by",
        "inventory_link",
    )
    if Campaign.objects.filter(is_current=True).exists():
        items = items.filter(campaign__is_current=True)
    return items


@login_required
def review_list(request):
    """Présente Envoyé SAGE ou la façade de contrôles, avec filtres SQL multiples.

    GET uniquement en lecture ; union dans chaque dimension et intersection
    entre dimensions. Le défaut est À examiner, propositions avant cas manuels.
    Les anciennes URLs match_status restent acceptées, sans widget dédié.
    Les preuves sont chargées pour la seule page autorisée du portefeuille.
    Le filtre suit l'ordre partagé de la cascade, sans trier ses libellés.
    Département filtre le rattachement transcodifié de la campagne courante,
    dans le seul portefeuille autorisé, avant compte et pagination.
    """
    if request.GET.get("view") == "controls":
        from .global_views import control_workspace
        return control_workspace(request)
    items = visible(request.user)
    items = items.filter(transaction__bap_status="Envoyé SAGE")
    scope = items
    projects = list(scope.order_by("transaction__project__code").values_list("transaction__project__code", flat=True).distinct())
    rules = rule_choices(list(scope.order_by("group__rule").values_list("group__rule", flat=True).distinct()))
    from .departments import department_filter
    campaign = Campaign.objects.filter(is_current=True).first()
    items, department_menu = department_filter(items, campaign, request, "transaction__project__code", has_projects=bool(projects))
    selected_projects = selections(request.GET, "project", projects)
    states = [("DRAFT", "À examiner"), ("VALIDATED", "Validé"), ("REJECTED", "Refusé")]
    state = selections(request.GET, "state", [key for key, _ in states], ("DRAFT",))
    rule = selections(request.GET, "rule", [key for key, _ in rules] + ["UNMATCHED"])
    origins = selections(request.GET, "validation_source", ["AUTO", "MANUAL"])
    match_status = request.GET.get("match_status", "")
    search = request.GET.get("q", "").strip()
    if match_status in ("MATCHED", "AMBIGUOUS", "UNMATCHED"):
        items = items.filter(group__match_status=match_status)
    if rule:
        selected_rules = [value for value in rule if value not in ("__NO_MATCH__", "UNMATCHED")]
        condition = Q(group__rule__in=selected_rules)
        if any(value in rule for value in ("__NO_MATCH__", "UNMATCHED")):
            condition |= no_match_query()
        items = items.filter(condition)
    if search:
        items = items.filter(
            Q(transaction__atlas_label__icontains=search)
            | Q(transaction__source_id__icontains=search)
            | Q(transaction__sage_bap_number__icontains=search)
            | Q(transaction__sage_third_party_code__icontains=search)
            | Q(transaction__third_party_name__icontains=search)
        )
    if selected_projects:
        items = items.filter(transaction__project__code__in=selected_projects)
    if state:
        stale = CampaignReview.objects.filter(campaign_id=OuterRef("campaign_id"), line_id=OuterRef("pk"),
            decision__current=False).exclude(decision__version=0)
        items = items.annotate(review_stale=Exists(stale))
        needs_review = Q(state="DRAFT") | Q(review_stale=True) | Q(source_signature="", version__gt=0)
        condition = Q(pk__in=[])
        if "DRAFT" in state:
            condition |= needs_review
        if "VALIDATED" in state:
            condition |= Q(state="VALIDATED") & ~needs_review
        if "REJECTED" in state:
            condition |= Q(state="REJECTED") & ~needs_review
        items = items.filter(condition)
    if origins:
        items = items.filter(validation_source__in=origins)
    size = request.GET.get("page_size", "50")
    size = int(size) if size in ("25", "50", "100") else 50
    items = items.annotate(work_priority=Case(When(no_match_query(), then=Value(1)), default=Value(0), output_field=IntegerField()))
    page = Paginator(items.order_by("work_priority", "transaction__project__code", "pk"), size).get_page(
        request.GET.get("page")
    )
    rows = list(page.object_list)
    groups = {
        row["group_id"]: row
        for row in LineReview.objects.filter(group_id__in={line.group_id for line in rows})
        .values("group_id")
        .annotate(
            n=Count("pk"),
            amounts=Count("transaction__total_project_charges"),
            atlas_total=Sum("transaction__total_project_charges"),
        )
    }
    for line in rows:
        decorate(line)
        summary = groups[line.group_id]
        line.atlas_count = summary["n"]
        line.sage_count = sum(len(candidate.get("rows", [])) for candidate in line.group.evidence)
        line.group_gap = (
            summary["atlas_total"] - line.group.sage_total
            if summary["amounts"] == summary["n"] and line.group.sage_total is not None
            else None
        )
    page.object_list = rows
    return render(
        request,
        "reconciliation/reviews.html",
        {
            "page": page,
            "campaign": campaign,
            "project": selected_projects[0] if len(selected_projects) == 1 else "",
            "state": state,
            "rule": rule,
            "match_status": match_status,
            "search": search,
            "page_size": size,
            "filter_menus": [filter_menu("project", "Projet", [(p, p) for p in projects], selected_projects),
                             department_menu,
                             filter_menu("rule", "Règle", rules, ["__NO_MATCH__" if r == "UNMATCHED" else r for r in rule]),
                             filter_menu("state", "Décision", states, state),
                             filter_menu("validation_source", "Origine", [("AUTO", "Automatique"), ("MANUAL", "Manuelle")], origins)],
            "page_range": page.paginator.get_elided_page_range(page.number, on_each_side=2),
        },
    )


@login_required
def review_detail(request, pk):
    """Présente les preuves autorisées et délègue les décisions atomiques de la revue pk.

    GET est sans effet métier. POST contrôle versions/signature et conserve le
    parcours existant ; les actions Lot 2 pointent vers la ligne exacte de
    campagne, où les sources et montants retenus restent distincts. Retourne
    HTML/redirection, affiche les ValidationError et masque les lignes hors droits.
    Les champs calculés depuis la sélection sont signalés au service, qui recharge
    les preuves et recalcule leurs charges Decimal avant toute écriture.
    """
    line = get_object_or_404(visible(request.user), pk=pk)
    return_url = safe_return(request.GET.get("return", ""))
    decorate(line)
    inventory = CampaignInventory.objects.filter(campaign_id=line.campaign_id, business_key=line.transaction.business_key,
        present=True).select_related("adjustment").first() if line.campaign_id else None
    actions = line_actions(line, inventory)
    initial = {
        "version": line.version,
        "group_version": line.group.version,
        "source": signature(line),
        "comment": line.comment,
        "manual_refs": [e["ref"] for e in line.manual_assignment],
    }
    for name in ("status", "amount", "document", "date"):
        value = line.values.get(name, {"mode": "KEEP"})
        initial[name + "_mode"] = value["mode"]
        initial[name] = value.get("value")
    if not line.values and line.group.match_status == "MATCHED":
        initial.update(status_mode="SET", status="Comptabilisé")
        proofs = [row for candidate in line.group.evidence for row in candidate.get("rows", [])]
        for name, source in (("document", "Numéro pièce"), ("date", "Date comptable")):
            distinct = {
                str(row[source])[:10] if name == "date" else str(row[source])
                for row in proofs
                if row.get(source)
            }
            if len(distinct) == 1:
                initial[name + "_mode"] = "SET"
                initial[name] = distinct.pop()
        if line.group.lines.count() == 1 and line.group.sage_total is not None:
            initial.update(amount_mode="SET", amount=line.group.sage_total)
    from .multiple_review import candidates_for

    manual_candidates = list(candidates_for(line).values())
    form = LineReviewForm(
        request.POST if request.method == "POST" else None,
        initial=initial,
        candidates=manual_candidates,
    )
    from .revision import RevisionForm, reopen_review
    revision = RevisionForm(request.POST if request.method == "POST" and request.POST.get("action") == "REVISE" else None,
                            initial={"version": line.version, "group_version": line.group.version, "source": signature(line)})
    if request.method == "POST" and request.POST.get("action") == "REVISE":
        if revision.is_valid():
            try:
                reopen_review(line.pk, request.user, version=revision.cleaned_data["version"],
                    group_version=revision.cleaned_data["group_version"], source=revision.cleaned_data["source"],
                    comment=revision.cleaned_data["comment"])
            except ValidationError as exc:
                revision.add_error(None, exc)
            else:
                messages.success(request, "Validation annulée et historisée. Vous pouvez rechercher une autre écriture Sage.")
                if inventory:
                    return redirect(reverse("reconciliation:inventory-detail", args=[inventory.pk]) + "?" +
                                    urlencode({"return": return_url}) + "#search")
                return redirect(request.get_full_path())
    elif request.method == "POST" and actions["confirmed"]:
        form.add_error(None, "Utilisez Réviser le rapprochement pour modifier une validation existante.")
    elif request.method == "POST" and form.is_valid():
        try:
            decide(
                line.pk,
                request.user,
                state=request.POST.get("action"),
                values=form.snapshot(),
                comment=form.cleaned_data["comment"],
                expected_version=form.cleaned_data["version"],
                expected_group_version=form.cleaned_data["group_version"],
                expected_source=form.cleaned_data["source"],
                acknowledge=request.POST.get("action") == "VALIDATED",
                manual_refs=form.cleaned_data["manual_refs"],
                selection_autofill=form.cleaned_data["selection_auto"],
                # La soumission enregistre le choix manuel ; Valider accepte
                # les risques recalculés. Les commentaires restent contrôlés.
                manual_confirm=True,
                multiple_confirm=request.POST.get("action") == "VALIDATED",
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Décision enregistrée et historisée pour cette ligne.")
            return redirect(request.get_full_path())
    siblings = list(visible(request.user).filter(group=line.group))
    total = Decimal("0")
    missing = 0
    for sibling in siblings:
        sibling.allocated = effective(sibling)["amount"]
        decorate(sibling)
        if sibling.state == "REJECTED" or sibling.stale:
            sibling.allocated = None
        if sibling.allocated is None:
            missing += 1
        else:
            total += sibling.allocated
    candidates = [
        {
            "id": candidate.get("id"),
            "rows": [
                {
                    "document": row.get("Numéro pièce"),
                    "bap": row.get("Référence"),
                    "date": row.get("Date comptable"),
                    "label": row.get("Libellé pièce"),
                    "amount": row.get("Charges (Dépenses)"),
                    "third_party": row.get("Code Tiers - Tiers doc Orig"),
                    "third_party_name": row.get("Nom du Tiers"),
                }
                for row in candidate.get("rows", [])
            ],
        }
        for candidate in line.group.evidence
        if candidate.get("rows")
    ]
    campaign_snapshot = line.campaign_reviews.select_related("group").filter(campaign_id=line.campaign_id).first() if line.campaign_id else None
    return render(
        request,
        "reconciliation/review_detail.html",
        {
            "piece_check": campaign_snapshot.group.data.get("piece_coherence") if campaign_snapshot else None,
            "piece_active": bool(line.campaign_id and line.campaign.metadata.get("piece_coherence_mode") == "ACTIVE"),
            "piece_assignment": line.automatic_assignment,
            "line": line,
            "business_inventory": inventory,
            "actions": actions, "revision": revision,
            "resolved": effective(line),
            "manual_candidates": manual_candidates,
            "selection_restore": {name: {"mode": initial.get(name + "_mode", "KEEP"),
                "value": "" if initial.get(name) is None else str(initial[name])}
                for name in ("amount", "document", "date")},
            "form": form,
            "return_url": return_url,
            "edit_fields": [
                {
                    "mode": form[name + "_mode"],
                    "value": form[name],
                    "name": name,
                    "source": getattr(line.transaction, source),
                }
                for name, source in (
                    ("status", "bap_status"),
                    ("amount", "total_sage_charges"),
                    ("document", "sage_document_number"),
                    ("date", "accounting_date"),
                )
            ],
            "siblings": siblings,
            "total": total,
            "missing": missing,
            "gap": total - line.group.sage_total if line.group.sage_total is not None else None,
            "stale": bool(line.version and not is_current(line)),
            "campaign_snapshot": campaign_snapshot,
            "candidates": candidates,
            "events": list(history_rows(line.events.select_related("actor")[:50])),
            "allocation_context": {
                "others": str(
                    sum(
                        s.allocated for s in siblings if s.pk != line.pk and s.allocated is not None
                    )
                ),
                "missing_others": sum(s.allocated is None for s in siblings if s.pk != line.pk),
                "source": str(line.transaction.total_sage_charges)
                if line.transaction.total_sage_charges is not None
                else None,
                "target": str(line.group.sage_total) if line.group.sage_total is not None else None,
            },
        },
    )


@login_required
def conservation_export(request):
    """Exporte les corrections valides sans y mélanger les brouillons ou refus."""
    campaign = Campaign.objects.filter(is_current=True).first()
    if campaign:
        from .campaign_views import campaign_export

        return campaign_export(request, campaign.pk)
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="conservation-validee.xlsx"'
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Corrections validées")
    sheet.append(
        [
            "Id",
            "Code projet",
            "Année",
            "Statut BAP",
            "Total charges SAGE (€)",
            "N° pièce SAGE",
            "Date comptable",
            "Commentaire",
            "Version",
            "Signature source",
        ]
    )
    items = visible(request.user).filter(state="VALIDATED")
    project = request.GET.get("project", "").strip()
    if project:
        items = items.filter(transaction__project__code=project)
    for line in items.iterator():
        if not is_current(line):
            continue
        resolved = effective(line)
        cells = []
        for value in [
            line.transaction.source_id,
            line.transaction.project.code,
            line.transaction.fiscal_year,
            resolved["status"],
            resolved["amount"],
            resolved["document"],
            resolved["date"],
            line.comment,
            line.version,
            line.source_signature,
        ]:
            cell = WriteOnlyCell(sheet, value)
            if isinstance(value, str):
                cell.data_type = "s"
            cells.append(cell)
        sheet.append(cells)
    workbook.save(response)
    return response
