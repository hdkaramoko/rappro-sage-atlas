"""Écrans de décision par ligne et fichier de conservation des validations."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from .models import Campaign, LineReview, ReconciliationTransaction
from .presentation import RULE_LABELS, decorate, history_rows
from .review import decide, effective, is_current, signature
from .review_forms import LineReviewForm


def visible(user):
    items = LineReview.objects.filter(
        transaction__in=ReconciliationTransaction.objects.visible_for(user)
    ).select_related(
        "transaction",
        "transaction__project",
        "group",
        "campaign",
        "validation_origin",
        "updated_by",
    )
    if Campaign.objects.filter(is_current=True).exists():
        items = items.filter(campaign__is_current=True)
    return items


@login_required
def review_list(request):
    items = visible(request.user)
    scope = items
    project = request.GET.get("project", "").strip()
    state = request.GET.get("state", "")
    match_status = request.GET.get("match_status", "MATCHED")
    rule = request.GET.get("rule", "")
    search = request.GET.get("q", "").strip()
    if match_status in ("MATCHED", "AMBIGUOUS", "UNMATCHED"):
        items = items.filter(group__match_status=match_status)
    if rule:
        items = items.filter(group__rule=rule)
    if search:
        items = items.filter(
            Q(transaction__atlas_label__icontains=search)
            | Q(transaction__source_id__icontains=search)
            | Q(transaction__sage_bap_number__icontains=search)
            | Q(transaction__sage_third_party_code__icontains=search)
            | Q(transaction__third_party_name__icontains=search)
        )
    if project:
        items = items.filter(transaction__project__code=project)
    if state in ("DRAFT", "VALIDATED", "REJECTED"):
        items = items.filter(state=state)
    size = request.GET.get("page_size", "50")
    size = int(size) if size in ("25", "50", "100") else 50
    page = Paginator(items.order_by("transaction__project__code", "pk"), size).get_page(
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
            "campaign": Campaign.objects.filter(is_current=True).first(),
            "project": project,
            "state": state,
            "rule": rule,
            "match_status": match_status,
            "search": search,
            "page_size": size,
            "projects": scope.order_by("transaction__project__code")
            .values_list("transaction__project__code", flat=True)
            .distinct(),
            "rules": [
                (value, RULE_LABELS.get(value, value))
                for value in scope.order_by("group__rule")
                .values_list("group__rule", flat=True)
                .distinct()
            ],
            "page_range": page.paginator.get_elided_page_range(page.number, on_each_side=2),
        },
    )


@login_required
def review_detail(request, pk):
    line = get_object_or_404(visible(request.user), pk=pk)
    # N'accepte comme retour qu'une URL relative de la liste métier.
    return_url = request.GET.get("return", "")
    list_url = reverse("reconciliation:reviews")
    if return_url.split("?", 1)[0] != list_url:
        return_url = list_url
    decorate(line)
    initial = {
        "version": line.version,
        "group_version": line.group.version,
        "source": signature(line),
        "comment": line.comment,
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
    form = LineReviewForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
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
    return render(
        request,
        "reconciliation/review_detail.html",
        {
            "line": line,
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
            "campaign_snapshot": line.campaign_reviews.filter(campaign_id=line.campaign_id).first()
            if line.campaign_id
            else None,
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
