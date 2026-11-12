"""Lecture Excel en mémoire et création atomique de comptes sans portefeuille."""

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

HEADERS = ("nom", "prénom", "username", "mdp")
SALT = "accounts.user-import.v1"


@dataclass
class UserRow:
    """Porte une ligne validée en mémoire ; le secret est exclu de sa représentation."""

    number: int
    last_name: str
    first_name: str
    username: str
    password: str = field(repr=False)


def can_import_users(user):
    """Autorise un compte actif staff ayant le droit existant de créer des utilisateurs."""
    model = get_user_model()
    return bool(user.is_authenticated and user.is_active and user.is_staff
                and user.has_perm(f"{model._meta.app_label}.add_{model._meta.model_name}"))


@sensitive_variables()
def parse_users(uploaded):
    """Retourne lignes, erreurs non sensibles et empreinte ; refuse tout classeur ambigu.

    Le fichier reste en mémoire, les quatre colonnes doivent être textuelles.
    Les lignes vides sont ignorées ; aucune donnée n'est écrite ou journalisée.
    """
    limit = settings.USER_IMPORT_MAX_BYTES
    if not uploaded.name.lower().endswith(".xlsx") or not 0 < uploaded.size <= limit:
        raise ValidationError(f"Sélectionnez un fichier .xlsx non vide, de {limit // 1024**2} Mo maximum.")
    uploaded.seek(0)
    content = uploaded.read(limit + 1)
    if len(content) > limit:
        raise ValidationError("Fichier trop volumineux.")
    workbook = None
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(item.file_size for item in entries) > 50 * 1024**2:
                raise ValidationError("Classeur trop volumineux après décompression.")
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
        if "data" not in workbook.sheetnames:
            raise ValidationError("Feuille attendue : data.")
        sheet = workbook["data"]
        if sheet.max_column != 4:
            raise ValidationError("Colonnes attendues exactement : nom, prénom, username, mdp.")
        iterator = sheet.iter_rows()
        header = next(iterator, ())
        if tuple(cell.value for cell in header) != HEADERS:
            raise ValidationError("En-têtes attendus exactement : nom, prénom, username, mdp.")
        rows, errors, seen = [], [], set()
        model = get_user_model()
        for number, cells in enumerate(iterator, 2):
            if number > settings.USER_IMPORT_MAX_ROWS + 1:
                raise ValidationError(f"Maximum : {settings.USER_IMPORT_MAX_ROWS} lignes de données.")
            values = [cell.value for cell in cells]
            if all(value in (None, "") for value in values):
                continue
            if any(cell.data_type in ("f", "e") for cell in cells):
                errors.append(f"Ligne {number} : formule ou cellule en erreur interdite.")
                continue
            if any(not isinstance(value, str) or not value.strip() for value in values):
                errors.append(f"Ligne {number} : les quatre champs doivent être des textes non vides (format Texte dans Excel).")
                continue
            last_name, first_name, username, password = values
            if username != username.strip() or model.normalize_username(username) != username:
                errors.append(f"Ligne {number} : identifiant ambigu, espaces ou normalisation Unicode à corriger.")
                continue
            candidate = model(username=username, first_name=first_name.strip(), last_name=last_name.strip())
            try:
                for name in ("username", "first_name", "last_name"):
                    model._meta.get_field(name).clean(getattr(candidate, name), candidate)
                if len(password) > 1024:
                    raise ValidationError("Longueur invalide.")
                validate_password(password, candidate)
            except ValidationError:
                errors.append(f"Ligne {number} : identifiant, nom, prénom ou mot de passe non conforme aux règles du serveur.")
                continue
            if username in seen:
                errors.append(f"Ligne {number} : username répété dans le fichier.")
            seen.add(username)
            rows.append(UserRow(number, candidate.last_name, candidate.first_name, username, password))
        if not rows and not errors:
            errors.append("Aucun utilisateur dans le classeur.")
        return rows, errors, sha256(content).hexdigest()
    except (BadZipFile, OSError, ValueError, TypeError, KeyError, IndexError, SyntaxError, EOFError, RuntimeError, InvalidFileException):
        raise ValidationError("Classeur Excel illisible ou endommagé.") from None
    finally:
        if workbook is not None:
            workbook.close()


def existing_usernames(rows):
    """Retourne les identifiants du fichier déjà en base, selon les comparaisons du backend."""
    model = get_user_model()
    # Une recherche exacte par ligne conserve les règles de collation du backend.
    return {row.username for row in rows if model.objects.filter(username=row.username).exists()}


@sensitive_variables()
def create_users(rows, actor):
    """Crée les seules lignes nouvelles atomiquement et retourne les numéros créés/ignorés.

    Aucun secret n'est persisté hors du hash utilisateur. Une collision concurrente
    annule l'ensemble et produit un motif générique sans contenu SQL sensible.
    """
    if not can_import_users(actor):
        raise PermissionDenied
    model = get_user_model()
    created, ignored = [], []
    try:
        with transaction.atomic():
            for row in rows:
                if model.objects.filter(username=row.username).exists():
                    ignored.append(row.number)
                    continue
                user = model(username=row.username, first_name=row.first_name, last_name=row.last_name,
                             is_active=True, is_staff=False, is_superuser=False, geography="")
                user.set_password(row.password)
                user.save(force_insert=True)
                from django.contrib.admin.models import ADDITION, LogEntry
                LogEntry.objects.log_actions(user_id=actor.pk, queryset=[user], action_flag=ADDITION,
                    change_message="Création via import Excel, sans portefeuille.")
                created.append(row.number)
    except IntegrityError:
        raise ValidationError("Conflit concurrent : aucun compte de cet import créé. Recommencez l’aperçu.") from None
    return created, ignored


def preview_token(fingerprint, actor):
    """Signe uniquement l'empreinte du fichier et l'acteur, sans stocker de secret ni de session intermédiaire."""
    return signing.dumps({"fingerprint": fingerprint, "actor": actor.pk}, salt=SALT)


def verify_preview(token, fingerprint, actor):
    """Valide une confirmation de moins de dix minutes portant sur le même fichier et administrateur."""
    try:
        payload = signing.loads(token, salt=SALT, max_age=600)
    except signing.BadSignature:
        raise ValidationError("Aperçu expiré ou invalide : recommencez le contrôle.") from None
    if payload != {"fingerprint": fingerprint, "actor": actor.pk}:
        raise ValidationError("Le fichier ou l’administrateur a changé : recommencez l’aperçu.")
