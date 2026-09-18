from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import PortfolioAddForm
from .models import Project, ProjectPortfolio


@login_required
def portfolio(request):
    """Affiche le portefeuille et traite l'ajout d'un projet connu."""
    form = PortfolioAddForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        project = Project.objects.filter(
            code=form.cleaned_data["project_code"], is_active=True
        ).first()
        if not project:
            form.add_error("project_code", "Ce code projet est introuvable dans le référentiel.")
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
