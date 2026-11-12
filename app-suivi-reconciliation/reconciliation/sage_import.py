"""Import par lots de l'extension d'inventaire Sage dans la transaction de campagne."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from reconciliation_contract import money
from reconciliation_contract.sage_inventory import CAPABILITY, exclusion_policy, ods_scope, validate_inventory_record

from .models import CampaignSageEntry


def validate_capabilities(header: dict) -> bool:
    """Valide capacités et politique figée ; retourne la présence du lot 1.

    L'absence conserve la lecture historique. Une capacité inconnue ou une
    signature/configuration invalide lève ValidationError avant toute écriture.
    """
    capabilities = header.get("capabilities", [])
    if not isinstance(capabilities, list) or capabilities not in ([], [CAPABILITY]):
        raise ValidationError("Capacités de campagne non prises en charge")
    enabled = CAPABILITY in capabilities
    if enabled:
        try:
            policy = header["sage_exclusions"]
            if header.get("schema_version") != 3 or policy != exclusion_policy(policy["prefixes"]):
                raise ValueError("Politique Sage incohérente")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Politique d'exclusion Sage invalide") from exc
    return enabled


def insert_sage_batch(campaign, rows: list[dict]) -> None:
    """Valide et insère au plus un lot d'écritures Sage pour `campaign`.

    Vérifie signatures, longueurs SQL et exercice ; l'unicité SQL refuse les
    record_id répétés, y compris entre lots. Les refs en collision restent des
    preuves distinctes. Une erreur lève ValidationError et annule l'import parent.
    """
    records = []
    try:
        for data in rows:
            validate_inventory_record(data, campaign.metadata["sage_exclusions"])
            entry = data["entry"]
            if len(entry["project_code"]) > 100 or len(entry["document"]) > 100:
                raise ValueError("Projet ou pièce Sage trop long")
            if campaign.fiscal_year is not None and entry["fiscal_year"] != campaign.fiscal_year:
                raise ValueError("Écriture Sage hors exercice")
            if entry["fiscal_year"] is not None and not 2000 <= entry["fiscal_year"] <= 2200:
                raise ValueError("Exercice Sage invalide")
            records.append(CampaignSageEntry(
                campaign=campaign, record_id=data["record_id"], entry_ref=entry["ref"],
                project_code=entry["project_code"], fiscal_year=entry["fiscal_year"],
                document=entry["document"], control_key=data["control_key"],
                ods_scope=ods_scope(entry, sage=True),
                amount=money(entry["amount"]), eligible=data["eligible"], data=data))
        with transaction.atomic():
            CampaignSageEntry.objects.bulk_create(records, batch_size=500)
    except (KeyError, TypeError, ValueError, IntegrityError) as exc:
        raise ValidationError(f"Inventaire Sage invalide ou répété : {exc}") from exc
