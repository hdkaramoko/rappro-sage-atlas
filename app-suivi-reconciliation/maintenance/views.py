"""Accès administratif de secours sans ouverture des parcours métier."""

from django.contrib.auth import login
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .forms import RecoveryAuthenticationForm
from .services import can_manage


@never_cache
@require_http_methods(["GET", "HEAD"])
def liveness(request):
    """Confirme uniquement que Django répond ; ne promet ni base disponible ni service métier ouvert."""
    return JsonResponse({"status": "alive"})


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def access(request):
    """Affiche le formulaire de récupération ; seuls les comptes de pilotage obtiennent une session.

    Les visiteurs et tentatives refusées reçoivent 503 ; aucun paramètre de retour
    ne permet une redirection vers un écran métier ou un domaine externe.
    """
    if can_manage(request.user):
        return redirect("admin:maintenance-pilot")
    form = RecoveryAuthenticationForm(request, data=request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("admin:maintenance-pilot")
    return render(request, "maintenance/access.html", {"form": form}, status=503)
