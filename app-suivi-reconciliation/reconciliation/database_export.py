"""Extraction JSON cohérente des données métier, réservée au superutilisateur."""

import json
from tempfile import TemporaryFile

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.http import FileResponse
from django.utils import timezone
from django.views.decorators.http import require_GET


def export_models():
    """Inclut sources, décisions, audits et accès ; exclut le compteur technique d'import."""
    for label in ("accounts", "projects", "reconciliation", "imports_app"):
        for model in apps.get_app_config(label).get_models():
            if model._meta.label_lower != "reconciliation.importrevision":
                yield model


def json_chunks():
    """Lit une photographie transactionnelle par lots sans charger la base en mémoire.

    Les identifiants et clés étrangères sont conservés. Les mots de passe,
    sessions et permissions internes Django ne font pas partie de l'extraction.
    La transaction englobe l'itération effective lors de la préparation du fichier.
    """
    encode = DjangoJSONEncoder(ensure_ascii=False).encode
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield '{\n"schema_version":1,\n"exported_at":' + encode(timezone.now()) + ',\n"tables":{\n'
        for index, model in enumerate(export_models()):
            fields = [f.attname for f in model._meta.concrete_fields if f.name != "password"]
            # Le manager par défaut masque les campagnes non publiées : une
            # extraction de la base conserve aussi ces lignes, avec leur statut.
            rows = model._base_manager.order_by("pk").values(*fields).iterator(chunk_size=500)
            yield (",\n" if index else "") + json.dumps(model._meta.label_lower) + ":[\n"
            for number, row in enumerate(rows):
                yield (",\n" if number else "") + encode(row)
            yield "\n]"
        yield "\n}\n}\n"


@login_required
@require_GET
def database_export(request):
    """Refuse les comptes simplement staff, même administrateurs globaux métier."""
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    # Préparer sur disque avant le téléchargement : un client lent ne doit
    # pas maintenir une transaction de lecture ouverte sur la base métier.
    output = TemporaryFile(mode="w+b")
    try:
        for chunk in json_chunks():
            output.write(chunk.encode("utf-8"))
        output.seek(0)
    except BaseException:
        output.close()
        raise
    response = FileResponse(output, content_type="application/json; charset=utf-8")
    stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    response["Content-Disposition"] = f'attachment; filename="base-reconciliation-{stamp}.json"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
