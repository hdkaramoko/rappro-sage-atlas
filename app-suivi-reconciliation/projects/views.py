from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from imports_app.views import administrator

from .forms import PortfolioAddForm, PortfolioImportForm
from .models import PortfolioImport, ProjectPortfolio
from .portfolio_import import import_portfolios, project_from_inventory


@login_required
def portfolio(request):
    """Affiche le portefeuille et traite l'ajout d'un projet connu."""
    form = PortfolioAddForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            project = project_from_inventory(form.cleaned_data["project_code"])
        except ValidationError as exc:
            form.add_error("project_code", exc)
        else:
            _, created = ProjectPortfolio.objects.get_or_create(user=request.user, project=project)
            messages.success(
                request,
                "Projet ajouté au portefeuille." if created else "Ce projet est déjà présent.",
            )
            return redirect("projects:portfolio")
    entries = request.user.portfolio_entries.select_related("project").order_by("project__code")
    return render(request, "projects/portfolio.html", {"entries": entries, "form": form})


@require_POST
@login_required
def portfolio_remove(request, pk: int):
    """Retire uniquement l'association de portefeuille demandée."""
    entry = get_object_or_404(ProjectPortfolio, pk=pk, user=request.user)
    entry.delete()
    messages.success(request, "Projet retiré du portefeuille ; ses données restent historisées.")
    return redirect("projects:portfolio")


@administrator
def portfolio_import(request):
    form = PortfolioImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            report = import_portfolios(form.cleaned_data["workbook"], request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                f"Import terminé : {report.created_count} accès ajoutés, "
                f"{report.existing_count} déjà présents. Aucun accès supprimé.",
            )
            return redirect("projects:portfolio-import")
    page = Paginator(PortfolioImport.objects.select_related("actor"), 20).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "projects/portfolio_import.html",
        {
            "form": form,
            "page": page,
            "page_range": page.paginator.get_elided_page_range(page.number),
        },
    )


@administrator
def portfolio_template(request):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Portefeuilles"
    sheet.append(["username", "code projet"])
    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 70
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="modele-portefeuilles.xlsx"'
    try:
        workbook.save(response)
    finally:
        workbook.close()
    return response
