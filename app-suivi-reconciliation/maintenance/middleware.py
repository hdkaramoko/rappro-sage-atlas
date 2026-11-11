"""Blocage des nouvelles requêtes avant CSRF, vues et opérations métier."""

import logging

from django.db import DatabaseError
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import Resolver404, resolve
from django.views.decorators.cache import never_cache

from .models import MaintenanceState
from .services import can_manage, current_state

logger = logging.getLogger(__name__)


class MaintenanceSafeSessionMiddleware(SessionMiddleware):
    """Conserve le comportement Django sauf pour les réponses explicitement sans accès aux sessions."""

    def process_response(self, request, response):
        """Évite une lecture de session lors d'une panne de configuration ou d'une sonde autonome.

        Django consulte normalement l'expiration même avant de décider de ne pas
        sauvegarder une réponse 503. Ici le cookie et la session restent intacts.
        """
        if getattr(request, "maintenance_stateless", False):
            return response
        return super().process_response(request, response)


@never_cache
def unavailable(request, *, configuration=None, incident=False):
    """Retourne un 503 autonome sans processeurs de contexte ni lecture métier.

    Une panne de configuration produit un message distinct, sans détails techniques.
    Aucune échéance de reprise fiable n'existe : aucun Retry-After n'est inventé.
    """
    html = render_to_string("maintenance/unavailable.html", {"configuration": configuration, "incident": incident})
    return HttpResponse(html, status=503)


class MaintenanceMiddleware:
    """Lit l'état sur chaque requête dynamique et ne laisse passer que la récupération et le pilotage."""

    def __init__(self, get_response):
        """Mémorise la suite de la chaîne sans lire la base au démarrage."""
        self.get_response = get_response

    def __call__(self, request):
        """Autorise ou bloque la requête courante ; ne suspend aucun traitement déjà entré."""
        try:
            response = self.check_request(request)
        except DatabaseError:
            request.maintenance_stateless = True
            logger.exception("Configuration de maintenance indisponible ; accès dynamique suspendu.")
            return unavailable(request, incident=True)
        return response if response is not None else self.get_response(request)

    def check_request(self, request):
        """Retourne un blocage ou None ; les erreurs de configuration remontent à l'appelant."""
        try:
            match = resolve(request.path_info)
        except Resolver404:
            match = None
        if match and match.view_name == "maintenance-liveness" and request.method in ("GET", "HEAD"):
            request.maintenance_stateless = True
            return None
        if match and match.func.__module__ == "django.contrib.staticfiles.views" and request.method in ("GET", "HEAD"):
            request.maintenance_stateless = True
            return None
        configuration = current_state()
        request.maintenance_state = configuration
        if configuration.state != MaintenanceState.State.ACTIVE:
            return None
        name = match.view_name if match else ""
        if name == "maintenance-access":
            return None
        if name in ("admin:index", "admin:maintenance_maintenancestate_changelist", "admin:maintenance-pilot") and can_manage(request.user):
            return None
        return unavailable(request, configuration=configuration)
