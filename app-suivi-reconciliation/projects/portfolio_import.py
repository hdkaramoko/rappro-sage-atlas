"""Affectations additives : comptes existants et projets attestés par l'inventaire."""

import re
import unicodedata
from zipfile import BadZipFile, ZipFile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max, Q
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from reconciliation.models import Campaign, CampaignInventory

from .models import PortfolioImport, Project, ProjectPortfolio

MAX_ROWS = 20_000
MAX_ASSIGNMENTS = 50_000


def reference_inventory():
    """Dernier inventaire complet de chaque exercice, sans réactiver les absences."""
    complete = Campaign.objects.filter(inventory_complete=True)
    all_years = complete.filter(fiscal_year__isnull=True).first()
    annual = complete.filter(fiscal_year__isnull=False)
    if all_years:
        annual = annual.filter(pk__gt=all_years.pk)
    latest = list(annual.order_by().values("scope", "fiscal_year").annotate(latest_id=Max("pk")))
    condition = Q(campaign_id__in=[row["latest_id"] for row in latest])
    if all_years:
        condition |= Q(campaign=all_years) & ~Q(
            fiscal_year__in=[row["fiscal_year"] for row in latest]
        )
    return CampaignInventory.objects.filter(condition, present=True)


def project_from_inventory(code):
    if not reference_inventory().filter(project_code=code).exists():
        raise ValidationError(
            "Code projet introuvable dans les derniers inventaires Atlas. "
            "Importez d'abord une campagne complète."
        )
    project, _ = Project.objects.get_or_create(
        code=code, defaults={"label": "Projet issu de l’inventaire Atlas"}
    )
    if not project.is_active:
        raise ValidationError("Ce projet est désactivé.")
    return project


def header_name(value):
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(char for char in text if char.isalnum() and not unicodedata.combining(char))


def parse_workbook(uploaded):
    """Lecture seule, formules refusées ; une erreur ne peut produire un import partiel."""
    if not str(uploaded.name).lower().endswith(".xlsx"):
        raise ValidationError("Le fichier doit être au format .xlsx.")
    try:
        with ZipFile(uploaded) as archive:
            if sum(item.file_size for item in archive.infolist()) > 50 * 1024**2:
                raise ValidationError(
                    "Classeur trop volumineux après décompression (50 Mo maximum)."
                )
        uploaded.seek(0)
        workbook = load_workbook(uploaded, read_only=True, data_only=False)
    except (BadZipFile, OSError, ValueError, KeyError, SyntaxError, InvalidFileException) as exc:
        raise ValidationError("Le fichier n'est pas un classeur Excel lisible.") from exc
    try:
        sheet = workbook.worksheets[0]
        if sheet.max_column != 2:
            raise ValidationError(
                "La première feuille doit contenir exactement deux colonnes : "
                "username et codes projets."
            )
        rows = sheet.iter_rows()
        header = next(rows, ())
        if (
            len(header) != 2
            or header_name(header[0].value) != "username"
            or header_name(header[1].value)
            not in ("codeprojet", "codesprojets", "projectcode", "projectcodes")
        ):
            raise ValidationError("En-têtes attendus : username et codes projets.")
        assignments = {}
        for number, row in enumerate(rows, 2):
            if number > MAX_ROWS + 1:
                raise ValidationError(f"Le fichier dépasse {MAX_ROWS} lignes de données.")
            values = [cell.value for cell in row]
            if all(value in (None, "") for value in values):
                continue
            if any(cell.data_type == "f" for cell in row):
                raise ValidationError(f"Ligne {number} : les formules ne sont pas acceptées.")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValidationError(
                    f"Ligne {number} : username et codes projets "
                    "doivent être renseignés comme textes."
                )
            username = values[0].strip()
            codes = [
                code.strip().upper() for code in re.split(r"[;,\n\r]+", values[1]) if code.strip()
            ]
            if not codes or len(username) > 150 or any(len(code) > 50 for code in codes):
                raise ValidationError(f"Ligne {number} : username ou code projet invalide.")
            for code in codes:
                assignments.setdefault((username, code), number)
            if len(assignments) > MAX_ASSIGNMENTS:
                raise ValidationError(f"Le fichier dépasse {MAX_ASSIGNMENTS} affectations.")
        if not assignments:
            raise ValidationError("Le classeur ne contient aucune affectation.")
        return assignments
    except (BadZipFile, OSError, ValueError, KeyError, IndexError, SyntaxError) as exc:
        raise ValidationError("Le contenu de la première feuille Excel est illisible.") from exc
    finally:
        workbook.close()


@transaction.atomic
def import_portfolios(uploaded, actor):
    if not actor.is_authenticated or not actor.is_global_admin:
        raise PermissionDenied
    assignments = parse_workbook(uploaded)
    users = {user.username: user for user in get_user_model().objects.filter(is_active=True)}
    codes = {code for _, code in assignments}
    known = set()
    inventory = reference_inventory()
    # Bornage des paramètres SQL, y compris sous SQLite.
    ordered_codes = sorted(codes)
    for offset in range(0, len(ordered_codes), 500):
        known.update(
            inventory.filter(project_code__in=ordered_codes[offset : offset + 500])
            .values_list("project_code", flat=True)
            .distinct()
        )
    inactive = set(Project.objects.filter(is_active=False).values_list("code", flat=True))
    errors = []
    for (username, code), number in assignments.items():
        if username not in users:
            errors.append(f"Ligne {number} : utilisateur inconnu ou inactif « {username} ».")
        if code not in known:
            errors.append(
                f"Ligne {number} : projet « {code} » absent des derniers inventaires Atlas."
            )
        elif code in inactive:
            errors.append(f"Ligne {number} : projet « {code} » désactivé.")
        if len(errors) >= 50:
            errors.append(
                "Corrigez ces erreurs avant de relancer ; le contrôle s'arrête aux 50 premières."
            )
            break
    if errors:
        raise ValidationError(errors)
    projects = {
        code: Project.objects.get_or_create(
            code=code, defaults={"label": "Projet issu de l’inventaire Atlas"}
        )[0]
        for code in sorted(codes)
    }
    created = 0
    for username, code in assignments:
        _, added = ProjectPortfolio.objects.get_or_create(
            user=users[username], project=projects[code]
        )
        created += int(added)
    return PortfolioImport.objects.create(
        actor=actor,
        filename=str(uploaded.name)[:255],
        created_count=created,
        existing_count=len(assignments) - created,
        assignments=[{"username": username, "project": code} for username, code in assignments],
    )
