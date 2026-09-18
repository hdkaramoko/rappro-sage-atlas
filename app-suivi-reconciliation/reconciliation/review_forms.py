from django import forms

MODES = [("KEEP", "Conserver"), ("SET", "Modifier"), ("CLEAR", "Effacer")]


class LineReviewForm(forms.Form):
    status_mode = forms.ChoiceField(label="Action sur le statut", choices=MODES)
    status = forms.CharField(label="Statut BAP", required=False, max_length=100)
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

    def clean(self):
        values = super().clean()
        for field in ("status", "amount", "document", "date"):
            if values.get(field + "_mode") == "SET" and values.get(field) in (None, ""):
                self.add_error(field, "Renseignez la valeur à remplacer.")
        return values

    def snapshot(self):
        return {
            name: {
                "mode": self.cleaned_data[name + "_mode"],
                "value": str(self.cleaned_data[name])
                if self.cleaned_data[name] is not None
                else None,
            }
            for name in ("status", "amount", "document", "date")
        }
