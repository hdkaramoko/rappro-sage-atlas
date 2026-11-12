"""Formulaires métier Lot 2, sans exposition des clés techniques de rapprochement."""

from uuid import uuid4

from django import forms

from .models import AtlasAdjustment


class BusinessActionForm(forms.Form):
    """Version et UUID cachés pour une action autorisée ; pas d'écriture en clean.

    Les services vérifient de nouveau droits, fraîcheur et capacité en transaction.
    Un commentaire est facultatif ici mais obligatoire pour confirmer un lien.
    """
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    request_id = forms.UUIDField(initial=uuid4, widget=forms.HiddenInput)
    comment = forms.CharField(label="Commentaire", required=False, max_length=2000,
                              widget=forms.Textarea(attrs={"rows": 2}))
    replace_existing = forms.BooleanField(label="Remplacer explicitement la décision ou l'affectation actuelle", required=False)


class AdjustmentForm(BusinessActionForm):
    """Saisie EUR à deux décimales ; un doublon ne demande pas de montant fictif.

    La correction est indépendante d'une validation. Les sources et leurs signes
    sont contrôlés par le service, pas réécrits par ce formulaire.
    """
    reason = forms.ChoiceField(label="Motif", choices=AtlasAdjustment.Reason.choices)
    amount = forms.DecimalField(label="Montant corrigé (€)", max_digits=18, decimal_places=2,
                                localize=True, required=False)

    def clean(self):
        """Retourne les valeurs nettoyées ; exige un montant pour Montant erroné.

        Lève l'erreur de champ Django si absent. Zéro reste une valeur explicite,
        distincte de l'exclusion Doublon. Aucun effet de bord.
        """
        values = super().clean()
        if values.get("reason") == AtlasAdjustment.Reason.AMOUNT and values.get("amount") is None:
            self.add_error("amount", "Renseignez le montant corrigé.")
        return values


class CancelLinkForm(BusinessActionForm):
    """Exige un motif, soumis par bouton explicite, pour retirer une association.

    Le service Lot 2 revérifie les droits et versions avant libération et audit.
    Aucun effet de bord au nettoyage du formulaire.
    """
    replace_existing = None
    comment = forms.CharField(label="Motif de l'annulation", max_length=2000,
                              widget=forms.Textarea(attrs={"rows": 2}))


class SageSearchForm(forms.Form):
    """Quatre filtres facultatifs sur l'inventaire du périmètre déjà autorisé.

    Le montant recherché est en EUR ; nettoyer ne lance aucun recalcul.
    """
    document = forms.CharField(label="Pièce", required=False, max_length=100)
    third_party = forms.CharField(label="Tiers", required=False, max_length=100)
    amount = forms.DecimalField(label="Montant (€)", max_digits=18, decimal_places=2, localize=True, required=False)
    label = forms.CharField(label="Libellé", required=False, max_length=200)
