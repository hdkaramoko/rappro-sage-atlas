import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.db import transaction
from openpyxl import load_workbook

from projects.models import Project
from reconciliation.models import ReconciliationTransaction

from .models import ImportBatch, TransactionObservation

NEW_COLUMN_MAP = {
    "Id": "source_id",
    "Code projet": "project_code",
    "Libellé projet": "source_project_label",
    "Année": "fiscal_year",
    "Activité": "activity",
    "Code ligne budgétaire": "budget_line_code",
    "Libellé ligne budgétaire": "budget_line_label",
    "Libellé ATLAS": "atlas_label",
    "Nature de dépense (ATLAS)": "atlas_expense_nature",
    "Code tiers SAGE": "sage_third_party_code",
    "Nom du tiers": "third_party_name",
    "N° BAP (SAGE)": "sage_bap_number",
    "Statut BAP": "bap_status",
    "Lieu de paiement": "payment_location",
    "Moyen de paiement": "payment_method",
    "Date comptable": "accounting_date",
    "N° pièce SAGE": "sage_document_number",
    "Total charges projet (€)": "total_project_charges",
    "Total charges SAGE (€)": "total_sage_charges",
    "Suggestion - Statut BAP": "suggestion_bap_status",
    "Suggestion - N° pièce SAGE": "suggestion_sage_document_number",
    "Suggestion - Date comptable": "suggestion_accounting_date",
    "Suggestion - Total charges SAGE (€)": "suggestion_total_sage_charges",
}
EXPECTED_COLUMNS = tuple(NEW_COLUMN_MAP)
LEGACY_COLUMNS = (
    "code_projet",
    "reference_transaction",
    "libelle",
    "date_transaction",
    "montant_atlas",
    "montant_sage",
    "statut_atlas",
    "statut_sage",
)
REQUIRED_NEW_VALUES = ("source_id", "project_code", "fiscal_year")


class ImportValidationError(ValueError):
    """Signale un fichier dont la structure ou une valeur interdit l'import."""


@dataclass(frozen=True)
class ImportResult:
    """Résume le résultat rendu à l'interface après import."""

    batch: ImportBatch
    duplicate: bool = False


def build_business_key(project_code: str, reference: str, fiscal_year: int | None = None) -> str:
    """Construit la clé stable projet/exercice/identifiant, compatible avec l'ancien format."""
    parts = [project_code.strip().upper()]
    if fiscal_year is not None:
        parts.append(str(fiscal_year))
    parts.append(reference.strip().upper())
    return "::".join(parts)


def _text(value) -> str:
    """Normalise une cellule textuelle sans produire la chaîne artificielle None."""
    return "" if value is None else str(value).strip()


def _decimal(value, row: int, column: str) -> Decimal | None:
    """Convertit un montant Excel ou français en décimal exact."""
    if value in (None, ""):
        return None
    normalized = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ImportValidationError(
            f"Ligne {row}, colonne « {column} » : montant invalide."
        ) from exc


def _date(value, row: int, column: str) -> date | None:
    """Convertit une date Excel ou ISO et conserve une cellule vide à NULL."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ImportValidationError(
            f"Ligne {row}, colonne « {column} » : date attendue AAAA-MM-JJ."
        ) from exc


def _parse_new(values: dict, row_number: int) -> dict:
    """Valide une ligne du nouveau format et prépare les champs canoniques et suggérés."""
    data = {internal: values.get(header) for header, internal in NEW_COLUMN_MAP.items()}
    for field in REQUIRED_NEW_VALUES:
        if data[field] in (None, ""):
            header = next(key for key, value in NEW_COLUMN_MAP.items() if value == field)
            raise ImportValidationError(
                f"Ligne {row_number}, colonne « {header} » : valeur obligatoire."
            )
    try:
        year = int(data["fiscal_year"])
    except (TypeError, ValueError) as exc:
        raise ImportValidationError(
            f"Ligne {row_number}, colonne « Année » : entier attendu."
        ) from exc
    if not 2000 <= year <= 2200:
        raise ImportValidationError(f"Ligne {row_number}, colonne « Année » : valeur hors limites.")
    text_fields = set(NEW_COLUMN_MAP.values()) - {
        "fiscal_year",
        "accounting_date",
        "suggestion_accounting_date",
        "total_project_charges",
        "total_sage_charges",
        "suggestion_total_sage_charges",
    }
    for field in text_fields:
        data[field] = _text(data[field])
    data["fiscal_year"] = year
    data["accounting_date"] = _date(data["accounting_date"], row_number, "Date comptable")
    data["suggestion_accounting_date"] = _date(
        data["suggestion_accounting_date"], row_number, "Suggestion - Date comptable"
    )
    data["total_project_charges"] = _decimal(
        data["total_project_charges"], row_number, "Total charges projet (€)"
    )
    data["total_sage_charges"] = _decimal(
        data["total_sage_charges"], row_number, "Total charges SAGE (€)"
    )
    data["suggestion_total_sage_charges"] = _decimal(
        data["suggestion_total_sage_charges"], row_number, "Suggestion - Total charges SAGE (€)"
    )
    return data


def _parse_legacy(values: dict, row_number: int) -> dict:
    """Convertit explicitement l'ancien format mock vers le nouveau domaine."""
    code = _text(values["code_projet"]).upper()
    reference = _text(values["reference_transaction"])
    if not code or not reference:
        raise ImportValidationError(f"Ligne {row_number} : code projet et référence obligatoires.")
    accounting_date = _date(values["date_transaction"], row_number, "date_transaction")
    atlas_amount = _decimal(values["montant_atlas"], row_number, "montant_atlas")
    sage_amount = _decimal(values["montant_sage"], row_number, "montant_sage")
    return {
        "project_code": code,
        "source_id": reference,
        "source_project_label": "",
        "fiscal_year": accounting_date.year if accounting_date else None,
        "atlas_label": _text(values["libelle"]),
        "accounting_date": accounting_date,
        "total_project_charges": atlas_amount,
        "total_sage_charges": sage_amount,
        "bap_status": _text(values["statut_atlas"]),
        "suggestion_bap_status": _text(values["statut_sage"]),
        "suggestion_total_sage_charges": sage_amount,
    }


def _headers(sheet) -> tuple[tuple[str, ...], str]:
    """Identifie strictement le nouveau ou l'ancien jeu d'en-têtes."""
    try:
        headers = tuple(_text(value) for value in next(sheet.iter_rows(values_only=True)))
    except StopIteration as exc:
        raise ImportValidationError("Le classeur ne contient aucune ligne d'en-tête.") from exc
    duplicates = sorted({header for header in headers if header and headers.count(header) > 1})
    if duplicates:
        raise ImportValidationError(f"En-têtes dupliqués : {', '.join(duplicates)}")
    if set(headers) == set(EXPECTED_COLUMNS):
        return headers, "new"
    if set(headers) == set(LEGACY_COLUMNS):
        return headers, "legacy"
    expected = EXPECTED_COLUMNS if "Id" in headers else LEGACY_COLUMNS
    missing = sorted(set(expected) - set(headers))
    unknown = sorted(set(headers) - set(expected))
    details = []
    if missing:
        details.append(f"colonnes manquantes : {', '.join(missing)}")
    if unknown:
        details.append(f"colonnes inconnues : {', '.join(unknown)}")
    raise ImportValidationError("Structure invalide — " + " ; ".join(details))


@transaction.atomic
def import_xlsx(uploaded_file, user) -> ImportResult:
    """Valide entièrement puis importe par upsert sans modifier aucune correction métier."""
    content = uploaded_file.read()
    digest = hashlib.sha256(content).hexdigest()
    existing = ImportBatch.objects.filter(file_hash=digest).first()
    if existing:
        return ImportResult(existing, duplicate=True)
    try:
        sheet = load_workbook(BytesIO(content), read_only=True, data_only=True).active
    except Exception as exc:
        raise ImportValidationError("Le classeur Excel est illisible.") from exc
    headers, file_format = _headers(sheet)
    parsed_rows = []
    seen_keys = set()
    for number, raw in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not any(value is not None for value in raw):
            continue
        values = dict(zip(headers, raw, strict=True))
        row = _parse_new(values, number) if file_format == "new" else _parse_legacy(values, number)
        key = (row["project_code"].upper(), row.get("fiscal_year"), row["source_id"].upper())
        if key in seen_keys:
            raise ImportValidationError(
                f"Ligne {number}, colonne « Id » : identifiant source dupliqué."
            )
        seen_keys.add(key)
        parsed_rows.append(row)
    batch = ImportBatch.objects.create(
        filename=uploaded_file.name,
        file_hash=digest,
        imported_by=user,
        status=ImportBatch.Status.SUCCESS,
        total_rows=len(parsed_rows),
    )
    for row in parsed_rows:
        project_code = row.pop("project_code").upper()
        project_label = row.get("source_project_label") or "Projet importé"
        project, _ = Project.objects.get_or_create(
            code=project_code, defaults={"label": project_label}
        )
        key = build_business_key(project.code, row["source_id"], row.get("fiscal_year"))
        defaults = {
            "project": project,
            **row,
            "reference": row["source_id"],
            "label": row.get("atlas_label", ""),
            "transaction_date": row.get("accounting_date"),
            "atlas_amount": row.get("total_project_charges"),
            "sage_amount": row.get("suggestion_total_sage_charges")
            if row.get("suggestion_total_sage_charges") is not None
            else row.get("total_sage_charges"),
            "atlas_status_source": row.get("bap_status", ""),
            "sage_status": row.get("suggestion_bap_status", ""),
        }
        item = ReconciliationTransaction.objects.filter(
            project=project, fiscal_year=row.get("fiscal_year"), source_id=row["source_id"]
        ).first()
        if item is None:
            item = ReconciliationTransaction.objects.filter(business_key=key).first()
        created = item is None
        if created:
            item = ReconciliationTransaction.objects.create(business_key=key, **defaults)
        if created:
            batch.created_rows += 1
        else:
            changed = any(getattr(item, field) != value for field, value in defaults.items())
            if changed:
                for field, value in defaults.items():
                    setattr(item, field, value)
                item.save()
                batch.updated_rows += 1
            else:
                batch.unchanged_rows += 1
        TransactionObservation.objects.create(batch=batch, transaction=item)
    batch.save()
    return ImportResult(batch)
