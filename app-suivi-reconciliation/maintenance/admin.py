"""Panneau intégré à l'Administration Django, sans édition directe du singleton."""

import logging

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.views.decorators.http import require_http_methods

from .forms import MaintenanceForm
from .models import MaintenanceEvent, MaintenanceState
from .services import can_manage, current_state, transition

logger = logging.getLogger(__name__)


@admin.register(MaintenanceState)
class MaintenanceAdmin(admin.ModelAdmin):
    """Expose un panneau unique et son audit aux seuls comptes de pilotage."""

    def has_module_permission(self, request):
        """Retourne la visibilité du module selon la permission dédiée, jamais selon le périmètre métier."""
        return can_manage(request.user)

    def has_view_permission(self, request, obj=None):
        """Autorise la consultation du panneau uniquement aux gestionnaires de maintenance."""
        return can_manage(request.user)

    def has_change_permission(self, request, obj=None):
        """Autorise la transition uniquement aux gestionnaires de maintenance."""
        return can_manage(request.user)

    def has_add_permission(self, request):
        """Interdit la création manuelle de configurations supplémentaires."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Interdit la suppression du singleton depuis l'Administration."""
        return False

    def get_urls(self):
        """Expose seulement les routes du panneau, sans édition ni actions standard contournables."""
        view = self.admin_site.admin_view(require_http_methods(["GET", "POST"])(self.pilot))
        return [path("", view, name="maintenance_maintenancestate_changelist"),
                path("pilot/", view, name="maintenance-pilot")]

    def pilot(self, request):
        """Affiche l'état et vingt événements ; sauvegarde atomiquement un formulaire POST autorisé."""
        if not can_manage(request.user):
            raise PermissionDenied
        configuration = current_state()
        form = MaintenanceForm(request.POST if request.method == "POST" else None, initial={
            "state": configuration.state, "message": configuration.message,
            "planned_at": configuration.planned_at, "version": configuration.version})
        status = 200
        if request.method == "POST" and form.is_valid():
            try:
                data = form.cleaned_data
                transition(state=data["state"], message=data["message"], planned_at=data["planned_at"],
                           version=data["version"], actor=request.user)
                messages.success(request, "État de maintenance enregistré.")
                return redirect("admin:maintenance-pilot")
            except ValidationError as exc:
                form.add_error(None, exc)
            except DatabaseError:
                logger.exception("Échec de la transition de maintenance.")
                form.add_error(None, "Enregistrement impossible. L’état n’a pas été confirmé ; rechargez la page.")
                status = 503
        return TemplateResponse(request, "maintenance/pilot.html", {
            **self.admin_site.each_context(request), "title": "Maintenance de l’application", "form": form,
            "configuration": configuration, "events": MaintenanceEvent.objects.order_by("-pk")[:20],
            "opts": self.model._meta}, status=status)
