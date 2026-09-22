from django import forms


class PortfolioAddForm(forms.Form):
    """Valide le code d'un projet à ajouter au portefeuille."""

    project_code = forms.CharField(label="Code projet", max_length=50)

    def clean_project_code(self) -> str:
        """Normalise le code saisi pour fiabiliser la recherche."""
        return self.cleaned_data["project_code"].strip().upper()


class PortfolioImportForm(forms.Form):
    workbook = forms.FileField(label="Affectations utilisateurs / projets (.xlsx)")

    def clean_workbook(self):
        uploaded = self.cleaned_data["workbook"]
        if not uploaded.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Sélectionnez un fichier .xlsx.")
        if not uploaded.size or uploaded.size > 10 * 1024**2:
            raise forms.ValidationError(
                "Le fichier doit contenir des données et ne pas dépasser 10 Mo."
            )
        return uploaded
