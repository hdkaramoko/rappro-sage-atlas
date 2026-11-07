"""Réouverture explicitement motivée d'une décision, via les services existants."""

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import Campaign, LineReview, ReconciliationTransaction, ReviewGroup
from .review import decide, signature


class RevisionForm(forms.Form):
    """Confirmation de révision : motif requis, versions et signature cachées.

    La saisie seule ne modifie rien ; reopen_review revérifie droits, campagne,
    état et fraîcheur. La case évite une annulation involontaire d'une validation.
    """
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    group_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    source = forms.CharField(widget=forms.HiddenInput)
    comment = forms.CharField(label="Pourquoi réviser ce rapprochement ?", max_length=2000,
                              widget=forms.Textarea(attrs={"rows": 2}))
    confirm_revision = forms.BooleanField(label="Je confirme l'annulation de cette validation et la libération de son affectation Sage.")


@transaction.atomic
def reopen_review(pk, user, *, version, group_version, source, comment):
    """Annule une validation AUTO ou MANUAL sans toucher aux sources ni à l'historique.

    Verrous campagne/groupe/ligne et versions recontrôlés avant decide(DRAFT).
    Les hooks Lot 2 libèrent les allocations, auditent et recalculent les seules
    cibles affectées. L'ancien état et son origine sont conservés dans ReviewEvent.
    PermissionDenied hors portefeuille ; ValidationError si close, périmée ou
    déjà rouverte. Retourne la LineReview réouverte, dans la même transaction.
    """
    entry = LineReview.objects.get(pk=pk)
    if entry.campaign_id:
        campaign = Campaign.objects.select_for_update().get(pk=entry.campaign_id)
        if not campaign.is_current:
            raise ValidationError("La campagne est close : révision impossible.")
    ReviewGroup.objects.select_for_update().get(pk=entry.group_id)
    line = LineReview.objects.select_for_update().select_related("group", "transaction", "inventory_link").get(pk=pk)
    if not user.is_active or not ReconciliationTransaction.objects.visible_for(user).filter(pk=line.transaction_id).exists():
        raise PermissionDenied
    if line.state != "VALIDATED" or not comment.strip():
        raise ValidationError("La révision exige une validation existante et un motif.")
    values = {name: line.values.get(name, {"mode": "KEEP"}) for name in ("status", "amount", "document", "date")}
    return decide(pk, user, state="DRAFT", values=values, comment=comment.strip(),
                  expected_version=version, expected_group_version=group_version, expected_source=source)
