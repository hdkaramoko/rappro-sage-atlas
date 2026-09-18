from django import forms
from django.conf import settings


class MatchingUploadForm(forms.Form):
    bundle = forms.FileField(label="Fichier de rapprochement (.jsonl)")

    def clean_bundle(self):
        uploaded = self.cleaned_data["bundle"]
        if not uploaded.name.lower().endswith(".jsonl"):
            raise forms.ValidationError("Sélectionnez le fichier .jsonl produit par le moteur.")
        if not uploaded.size or uploaded.size > settings.MATCHING_MAX_FILE_BYTES:
            raise forms.ValidationError("Fichier vide ou dépassant la taille maximale autorisée.")
        return uploaded
