"""Parcours administratif avec aperçu sûr et retransmission du classeur à confirmer."""

from io import BytesIO

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.db import DatabaseError
from django.template.response import TemplateResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from .user_import import can_import_users, create_users, existing_usernames, parse_users, preview_token, verify_preview


class UserImportMemoryHandler(FileUploadHandler):
    """Réceptionne le classeur exclusivement en RAM, avec plafond cumulé avant tout traitement CSRF."""

    def __init__(self, request):
        """Initialise le compteur de réception pour cette seule requête sans fichier temporaire."""
        super().__init__(request)
        self.received = 0

    def new_file(self, *args, **kwargs):
        """Prépare un tampon mémoire pour le fichier courant sans ouvrir de chemin disque."""
        super().new_file(*args, **kwargs)
        self.buffer = BytesIO()

    def receive_data_chunk(self, raw_data, start):
        """Stocke le fragment ou interrompt le téléversement au plafond ; ne transmet rien à un handler disque."""
        self.received += len(raw_data)
        if self.received > settings.USER_IMPORT_MAX_BYTES:
            self.request.user_import_too_large = True
            self.buffer.close()
            raise StopUpload(connection_reset=False)
        self.buffer.write(raw_data)
        return None

    def file_complete(self, file_size):
        """Retourne un fichier mémoire Django pour validation, sans persistance intermédiaire."""
        self.buffer.seek(0)
        return InMemoryUploadedFile(self.buffer, self.field_name, self.file_name, self.content_type, file_size, self.charset)


class UserImportForm(forms.Form):
    """Accepte un classeur à chaque étape et un jeton signé non sensible à la confirmation."""

    workbook = forms.FileField(label="Fichier utilisateurs (.xlsx)")
    token = forms.CharField(required=False, widget=forms.HiddenInput)
    action = forms.ChoiceField(choices=[("preview", "Contrôler"), ("confirm", "Confirmer")], widget=forms.HiddenInput)


@sensitive_variables()
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def import_users(request):
    """Affiche l'aperçu expurgé ou crée les comptes après relecture et confirmation signée.

    Toute anomalie rejette le classeur entier ; les comptes déjà présents sont
    ignorés sans modification. Les exceptions de base ne révèlent aucune valeur.
    """
    if not can_import_users(request.user):
        raise PermissionDenied
    form = UserImportForm(request.POST if request.method == "POST" else None, request.FILES or None,
                          initial={"action": "preview"})
    preview, result, token = [], None, ""
    errors = []
    uncertain = False
    if request.method == "POST":
        if getattr(request, "user_import_too_large", False):
            errors.append("Fichier trop volumineux. Réduisez sa taille avant de recommencer.")
        elif form.is_valid():
            try:
                rows, errors, fingerprint = parse_users(form.cleaned_data["workbook"])
                existing = existing_usernames(rows)
                # Seules ces valeurs publiques sont transmises au moteur de templates.
                preview = [{"number": row.number, "username": row.username, "first_name": row.first_name,
                            "last_name": row.last_name, "existing": row.username in existing} for row in rows]
                if not errors:
                    if form.cleaned_data["action"] == "confirm":
                        verify_preview(form.cleaned_data["token"], fingerprint, request.user)
                        created, ignored = create_users(rows, request.user)
                        result = {"created": created, "ignored": ignored}
                    else:
                        token = preview_token(fingerprint, request.user)
            except ValidationError as exc:
                errors.extend(exc.messages)
            except DatabaseError:
                uncertain = True
                errors.append("Base indisponible : résultat non confirmé. Vérifiez les comptes avant de recommencer.")
    return TemplateResponse(request, "admin/accounts/user_import.html", {
        **admin.site.each_context(request), "title": "Importer des utilisateurs", "form": form,
        "preview": preview, "errors": errors, "result": result, "token": token, "uncertain": uncertain,
        "create_count": sum(not row["existing"] for row in preview),
        "max_rows": settings.USER_IMPORT_MAX_ROWS, "max_mb": settings.USER_IMPORT_MAX_BYTES // 1024**2})
