from django import forms


class PortfolioAddForm(forms.Form):
    """Valide le code d'un projet à ajouter au portefeuille."""

    project_code = forms.CharField(label="Code projet", max_length=50)

    def clean_project_code(self) -> str:
        """Normalise le code saisi pour fiabiliser la recherche."""
        return self.cleaned_data["project_code"].strip().upper()
