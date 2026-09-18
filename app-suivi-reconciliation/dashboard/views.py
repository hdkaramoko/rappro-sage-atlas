"""Indicateurs des décisions métier sur les propositions importées."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404
from django.shortcuts import render

from projects.models import Project
from reconciliation.review import is_current
from reconciliation.review_views import visible


@login_required
def index(request):
    projects = Project.objects.filter(is_active=True).order_by("code")
    if not request.user.is_global_admin:
        projects = projects.filter(portfolio_entries__user=request.user).distinct()
    selected_project = request.GET.get("project", "").strip()
    items = visible(request.user)
    if selected_project:
        if not projects.filter(code=selected_project).exists():
            raise Http404("Projet inaccessible.")
        items = items.filter(transaction__project__code=selected_project)
    counts = {"draft": 0, "validated": 0, "rejected": 0, "stale": 0}
    states = {"DRAFT": "draft", "VALIDATED": "validated", "REJECTED": "rejected"}
    for row in items.filter(version=0).values("state").annotate(n=Count("pk")):
        counts[states[row["state"]]] += row["n"]
    for line in items.filter(version__gt=0).iterator(chunk_size=500):
        key = "stale" if line.version and not is_current(line) else states[line.state]
        counts[key] += 1
    return render(
        request,
        "dashboard/index.html",
        {
            "projects": projects,
            "selected_project": selected_project,
            "total": sum(counts.values()),
            "counts": counts,
            "projects_count": projects.filter(code=selected_project).count()
            if selected_project
            else projects.count(),
            "review_rate": round(counts["validated"] * 100 / sum(counts.values()))
            if sum(counts.values())
            else 0,
            "pending": counts["draft"] + counts["stale"],
        },
    )
