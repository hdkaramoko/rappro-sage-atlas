"""Affectations additives : comptes existants et projets attestés par l'inventaire."""

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
                "username et code projet."
            )
        rows = sheet.iter_rows()
        header = next(rows, ())
        if (
            len(header) != 2
            or header_name(header[0].value) != "username"
            or header_name(header[1].value) != "codeprojet"
        ):
            raise ValidationError("En-têtes attendus : username et code projet.")
        records = []
        for number, row in enumerate(rows, 2):
            if number > MAX_ROWS + 1:
                raise ValidationError(f"Le fichier dépasse {MAX_ROWS} lignes de données.")
            values = [cell.value for cell in row]
            if all(value in (None, "") or (isinstance(value, str) and not value.strip()) for value in values):
                continue
            username, code = (str(value or "").strip() for value in values)
            code = code.upper()
            reason = ""
            if any(cell.data_type == "f" for cell in row):
                reason = "Les formules ne sont pas acceptées."
            elif any(not isinstance(value, str) or not value.strip() for value in values):
                reason = "Username et code projet doivent être renseignés comme textes."
            elif any(separator in code for separator in (";", ",", "\n", "\r")):
                reason = "Renseignez un seul code projet par ligne, sans séparateur."
            elif len(username) > 150 or len(code) > 50:
                reason = "Username ou code projet invalide."
            records.append({"line": number, "username": username, "project": code, "reason": reason})
        if not records:
            raise ValidationError("Le classeur ne contient aucune affectation.")
        return records
    except (BadZipFile, OSError, ValueError, KeyError, IndexError, SyntaxError) as exc:
        raise ValidationError("Le contenu de la première feuille Excel est illisible.") from exc
    finally:
        workbook.close()


def batches(values):
    values = list(values)
    for offset in range(0, len(values), 500):
        yield values[offset:offset + 500]


def import_portfolios(uploaded, actor):
    if not actor.is_authenticated or not actor.is_global_admin:
        raise PermissionDenied
    records = parse_workbook(uploaded)
    users = {}
    for names in batches({row["username"] for row in records}):
        users.update((user.username, user) for user in get_user_model().objects.filter(username__in=names))
    codes = {row["project"] for row in records if not row["reason"]}
    known, projects = set(), {}
    inventory = reference_inventory()
    for chunk in batches(codes):
        known.update(inventory.filter(project_code__in=chunk).values_list("project_code", flat=True))
        projects.update((project.code, project) for project in Project.objects.filter(code__in=chunk))
    seen, valid, anomalies = {}, [], []
    duplicates = 0
    for row in records:
        key = (row["username"], row["project"])
        user = users.get(row["username"])
        project = projects.get(row["project"])
        if not row["reason"]:
            if key in seen:
                row["reason"] = f"Doublon du couple déjà renseigné à la ligne {seen[key]}."
                row["kind"] = "duplicate"
                duplicates += 1
            else:
                seen[key] = row["line"]
                if user is None:
                    row["reason"] = "Utilisateur inexistant."
                elif not user.is_active:
                    row["reason"] = "Utilisateur inactif."
                elif row["project"] not in known:
                    row["reason"] = "Projet absent des derniers inventaires Atlas."
                elif project and not project.is_active:
                    row["reason"] = "Projet désactivé."
        if row["reason"]:
            row.setdefault("kind", "rejected")
            anomalies.append(row)
        else:
            valid.append(row)
    # Les contraintes en base protègent aussi les imports concurrents.
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=actor.pk)
        valid_codes = {row["project"] for row in valid}
        Project.objects.bulk_create([
            Project(code=code, label="Projet issu de l’inventaire Atlas")
            for code in valid_codes if code not in projects
        ], batch_size=500, ignore_conflicts=True)
        for chunk in batches(valid_codes):
            projects.update((project.code, project) for project in Project.objects.filter(code__in=chunk))
        existing = set()
        for chunk in batches({users[row["username"]].pk for row in valid}):
            existing.update(ProjectPortfolio.objects.filter(user_id__in=chunk).values_list("user_id", "project_id"))
        entries = []
        for row in valid:
            key = (users[row["username"]].pk, projects[row["project"]].pk)
            if key not in existing:
                entries.append(ProjectPortfolio(user_id=key[0], project_id=key[1]))
        ProjectPortfolio.objects.bulk_create(entries, batch_size=500)
        rejected = len(anomalies) - duplicates
        status = "rejected" if not valid else ("partial" if rejected else "success")
        return PortfolioImport.objects.create(
            actor=actor, filename=str(uploaded.name)[:255],
            created_count=len(entries), existing_count=len(valid) - len(entries),
            analyzed_count=len(records), rejected_count=rejected, duplicate_count=duplicates,
            status=status, anomalies=anomalies,
            assignments=[{"username": row["username"], "project": row["project"]} for row in valid],
        )
