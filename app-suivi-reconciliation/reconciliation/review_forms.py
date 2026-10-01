from django import forms

from .statuses import BAP_CHOICES

MODES = [("KEEP", "Conserver"), ("SET", "Modifier"), ("CLEAR", "Effacer")]


class LineReviewForm(forms.Form):
    """Saisie des corrections et confirmations, recontrôlées dans le service métier."""

    manual_refs = forms.MultipleChoiceField(
        label="Option retenue", required=False, widget=forms.CheckboxSelectMultiple
    )
    status_mode = forms.ChoiceField(label="Action sur le statut", choices=MODES)
    status = forms.ChoiceField(
        label="Statut BAP", required=False, choices=[("", "Choisir un statut"), *BAP_CHOICES]
    )
    amount_mode = forms.ChoiceField(label="Action sur le montant", choices=MODES)
    amount = forms.DecimalField(
        label="Montant Sage affecté à cette ligne", required=False, max_digits=18, decimal_places=2
    )
    document_mode = forms.ChoiceField(label="Action sur la pièce", choices=MODES)
    document = forms.CharField(label="N° pièce Sage", required=False, max_length=100)
    date_mode = forms.ChoiceField(label="Action sur la date", choices=MODES)
    date = forms.DateField(
        label="Date comptable",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    comment = forms.CharField(label="Commentaire", required=False, widget=forms.Textarea)
    version = forms.IntegerField(widget=forms.HiddenInput)
    group_version = forms.IntegerField(widget=forms.HiddenInput)
    source = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, candidates=(), **kwargs):
        """Construit les choix uniquement avec les preuves transmises par le moteur."""
        super().__init__(*args, **kwargs)
        self.fields["manual_refs"].choices = [
            (
                e["ref"],
                f"{e['project_code']} · {e['document']} · {e['date']} · {e['amount']} € "
                f"· ligne comptable {e['line']} / analytique {e['analytic_line']}",
            )
            for e in candidates
        ]

    def clean(self):
        """Exige une valeur pour SET ; la cohérence comptable reste côté service."""
        values = super().clean()
        for field in ("status", "amount", "document", "date"):
            if values.get(field + "_mode") == "SET" and values.get(field) in (None, ""):
                self.add_error(field, "Renseignez la valeur à remplacer.")
        return values

    def snapshot(self):
        """Sérialise KEEP/SET/CLEAR sans perdre l'intention d'effacer un champ."""
        return {
            name: {
                "mode": self.cleaned_data[name + "_mode"],
                "value": str(self.cleaned_data[name])
                if self.cleaned_data[name] is not None
                else None,
            }
            for name in ("status", "amount", "document", "date")
        }
