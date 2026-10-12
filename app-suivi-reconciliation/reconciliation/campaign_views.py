"""Consultation des photographies et différences, toujours limitée au portefeuille."""

import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from projects.models import Project

from .campaigns import LABELS
from .models import Campaign, CampaignInventory, CampaignReview, ReviewEvent
from .presentation import history_rows

CHANGES = {
    "NEW": "Nouvelle ligne",
    "UNCHANGED": "Inchangée",
    "CHANGED": "Modifiée",
    "ABSENT": "Absente de l'extraction",
    "RETURNED": "Réapparue",
}
COMPARISONS = {
    "NEW": "Nouvelle revue",
    "UNCHANGED": "Contexte inchangé",
    "CHANGED": "À revoir",
    "CARRIED": "Validation reprise",
}


def projects_for(user):
    """Retourne les projets consultables par cet utilisateur."""
    items = Project.objects.all()
    return items if user.is_global_admin else items.filter(portfolio_entries__user=user)


def inventory_for(user):
    """Filtre les inventaires historiques selon les projets autorisés."""
    rows = CampaignInventory.objects.filter(campaign__published=True)
    return (
        rows
        if user.is_global_admin
        else rows.filter(project_code__in=projects_for(user).values("code"))
    )


def reviews_for(user):
    """Charge les photographies autorisées sans dépendre des sources courantes."""
    return CampaignReview.objects.filter(
        campaign__published=True, project__in=projects_for(user)
    ).select_related("campaign", "group", "project")


def campaigns_for(user):
    """Rend consultables les campagnes contenant des projets du portefeuille."""
    if user.is_global_admin:
        return Campaign.objects.all()
    ids = inventory_for(user).values("campaign_id")
    reviewed = reviews_for(user).values("campaign_id")
    return Campaign.objects.filter(Q(pk__in=ids) | Q(pk__in=reviewed))


@login_required
@require_GET
def campaign_list(request):
    """Présente les campagnes accessibles avec pagination."""
    page = Paginator(campaigns_for(request.user), 25).get_page(request.GET.get("page"))
    return render(
        request,
        "reconciliation/campaigns.html",
        {"page": page, "page_range": page.paginator.get_elided_page_range(page.number)},
    )


@login_required
@require_GET
def campaign_detail(request, pk):
    """Expose les différences d’inventaire et décisions de cette photographie."""
    campaign = get_object_or_404(campaigns_for(request.user), pk=pk)
    inventory = inventory_for(request.user).filter(campaign=campaign)
    reviews = reviews_for(request.user).filter(campaign=campaign)
    project = request.GET.get("project", "").strip()
    if project:
        inventory = inventory.filter(project_code=project)
        reviews = reviews.filter(project__code=project)
    counts = [
        {"label": CHANGES.get(row["change"], row["change"]), "value": row["n"]}
        for row in inventory.values("change").annotate(n=Count("pk"))
    ]
    tab = request.GET.get("tab", "reviews")
    query = request.GET.get("q", "").strip()
    change = request.GET.get("change", "")
    rows = inventory if tab == "inventory" else reviews
    if tab == "inventory":
        if change in CHANGES:
            rows = rows.filter(change=change)
        if query:
            rows = rows.filter(source_id__icontains=query)
    else:
        tab = "reviews"
        if change in COMPARISONS:
            rows = rows.filter(comparison=change)
        if query:
            rows = rows.filter(source__source_id__icontains=query)
    page = Paginator(rows.order_by("pk"), 50).get_page(request.GET.get("page"))
    for row in page:
        if tab == "inventory":
            row.change_label = CHANGES[row.change]
            row.details = [
                {"label": LABELS.get(key, key), **value} for key, value in row.differences.items()
            ]
            status = row.differences.get("bap_status", {})
            row.exited_matching = (
                status.get("before") == "Envoyé SAGE" and status.get("after") != "Envoyé SAGE"
            )
        else:
            row.comparison_label = COMPARISONS.get(row.comparison, row.comparison)
            row.validation_date = parse_datetime(row.decision.get("validated_at") or "")
    return render(
        request,
        "reconciliation/campaign.html",
        {
            "campaign": campaign,
            "counts": counts,
            "page": page,
            "tab": tab,
            "project": project,
            "query": query,
            "change": change,
            "changes": CHANGES.items() if tab == "inventory" else COMPARISONS.items(),
            "projects": projects_for(request.user).order_by("code"),
            "page_range": page.paginator.get_elided_page_range(page.number),
        },
    )


@login_required
@require_GET
def campaign_review(request, pk):
    """Affiche une revue historique, ses preuves et événements sans modification."""
    row = get_object_or_404(reviews_for(request.user), pk=pk)
    source_labels = {
        "source_id": "Id Atlas",
        "project_code": "Projet",
        "fiscal_year": "Année",
        "source_project_label": "Libellé projet",
        "atlas_label": "Libellé Atlas",
        "activity": "Activité",
        "budget_line_code": "Code ligne budgétaire",
        "budget_line_label": "Libellé ligne budgétaire",
        "atlas_expense_nature": "Nature de dépense Atlas",
        "sage_third_party_code": "Code tiers SAGE",
        "third_party_name": "Nom du tiers",
        "sage_bap_number": "BAP SAGE",
        "bap_status": "Statut BAP",
        "payment_location": "Lieu de paiement",
        "payment_method": "Moyen de paiement",
        "total_project_charges": "Charges projet (€)",
        "total_sage_charges": "Charges SAGE (€)",
        "rebillable_amount": "Montant refacturables",
        "planned_unit_price": "Prix unitaire prévu",
        "unit_count": "Nombre d'unités",
        "sage_document_number": "Pièce dans Atlas",
        "accounting_date": "Date comptable",
    }
    events = ReviewEvent.objects.filter(line_id=row.line_id, campaign=row.campaign).select_related(
        "actor"
    )
    return render(
        request,
        "reconciliation/campaign_review.html",
        {
            "snapshot": row,
            "source_fields": [(label, row.source.get(key)) for key, label in source_labels.items()],
            "comparison_label": COMPARISONS.get(row.comparison, row.comparison),
            "validated_at": parse_datetime(row.decision.get("validated_at") or ""),
            "events": list(history_rows(events[:50])),
            "siblings": reviews_for(request.user).filter(group=row.group),
        },
    )


@login_required
@require_GET
def campaign_export(request, pk):
    """Exporte les corrections actuelles dans la photographie choisie, avec provenance."""
    campaign = get_object_or_404(campaigns_for(request.user), pk=pk)
    rows = reviews_for(request.user).filter(
        campaign=campaign, decision__state="VALIDATED", decision__current=True
    )
    project = request.GET.get("project", "").strip()
    if project:
        rows = rows.filter(project__code=project)
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="conservation-campagne-{campaign.pk}.xlsx"'
    )
    book = Workbook(write_only=True)
    headers = [
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
        "Campagne",
        "Date de validation",
        "Validé par",
        "Campagne de validation d'origine",
        "Validation reprise",
        "Affectation métier",
        "Écritures SAGE affectées",
        "Diagnostic multiples",
    ]
    sheet = book.create_sheet("Corrections validées")
    sheet.append(headers)
    count, part = 0, 1
    try:
        for row in rows.iterator(chunk_size=500):
            if count == 1_048_575:
                part += 1
                sheet = book.create_sheet(f"Corrections {part}")
                sheet.append(headers)
                count = 0
            decision, source = row.decision, row.source
            resolved = decision["effective"]
            values = [
                source["source_id"],
                source["project_code"],
                source["fiscal_year"],
                resolved["status"],
                Decimal(str(resolved["amount"])),
                resolved["document"],
                resolved["date"],
                decision["comment"],
                decision["version"],
                decision["source_signature"],
                campaign.name,
                decision.get("validated_at"),
                decision.get("actor"),
                decision.get("origin_name"),
                decision.get("origin_id") != campaign.pk,
                "MANUAL_MATCH" if decision.get("manual_assignment") else "",
                json.dumps(decision.get("manual_assignment", []), ensure_ascii=False),
                json.dumps(decision.get("multiple_diagnostic", {}), ensure_ascii=False),
            ]
            cells = []
            for value in values:
                cell = WriteOnlyCell(sheet, value)
                if isinstance(value, str):
                    cell.data_type = "s"
                cells.append(cell)
            sheet.append(cells)
            count += 1
        book.save(response)
    finally:
        book.close()
    return response
