"""Saisie explicite de l'état et authentification de récupération administrative."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .models import MaintenanceState
from .services import can_manage


class MaintenanceForm(forms.Form):
    """Valide les champs du panneau et impose la confirmation de tout enregistrement actif."""

    state = forms.ChoiceField(label="État", choices=MaintenanceState.State.choices)
    message = forms.CharField(label="Message aux utilisateurs", max_length=2000, required=False,
                              widget=forms.Textarea(attrs={"rows": 3}))
    planned_at = forms.DateTimeField(label="Début prévisionnel (facultatif)", required=False,
                                    widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    confirm_active = forms.BooleanField(label="Je confirme le blocage des nouvelles requêtes des collaborateurs.", required=False)

    def clean(self):
        """Retourne les données valides ; refuse ACTIVE sans confirmation explicite."""
        data = super().clean()
        if data.get("state") == MaintenanceState.State.ACTIVE and not data.get("confirm_active"):
            raise ValidationError("Confirmez explicitement l’activation du blocage.")
        return data


class RecoveryAuthenticationForm(AuthenticationForm):
    """Authentifie uniquement les administrateurs autorisés, sans session pour les autres comptes."""

    def confirm_login_allowed(self, user):
        """Refuse les comptes sans permission de pilotage avec un message générique."""
        super().confirm_login_allowed(user)
        if not can_manage(user):
            raise ValidationError("Accès administratif non autorisé.", code="invalid_login")
