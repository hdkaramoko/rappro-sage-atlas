"""Publication atomique des campagnes et report explicable des décisions.

La projection courante reste compatible avec les écrans métier. Les photographies
conservent leurs propres sources et preuves : aucune lecture historique ne dépend
des valeurs mutables de ReconciliationTransaction ou ReviewGroup.
"""

import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import Subquery

from imports_app.services import build_business_key

from .models import (
    Campaign,
    CampaignGroup,
    CampaignInventory,
    CampaignReview,
    LineReview,
    ReviewEvent,
)
from .review import effective, is_current, signature, source_snapshot

INVENTORY = {
    "Code projet": "project_code",
    "Année": "fiscal_year",
    "Id": "source_id",
    "Statut BAP": "bap_status",
    "Total charges projet (€)": "total_project_charges",
    "Total charges SAGE (€)": "total_sage_charges",
    "N° pièce SAGE": "sage_document_number",
    "Date comptable": "accounting_date",
}
LABELS = {value: key for key, value in INVENTORY.items()}
BATCH_SIZE = 500


def json_data(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False))


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def stable_evidence(evidence):
    """Les numéros techniques des candidats et l'ordre source ne sont pas une preuve métier."""
    return sorted(
        [
            sorted(candidate.get("rows", []), key=lambda row: json.dumps(row, sort_keys=True))
            for candidate in evidence
        ],
        key=lambda rows: json.dumps(rows, sort_keys=True),
    )


def normalize_inventory(raw):
    """Schéma étroit : pas de création d'un objet ORM Atlas pour chaque ligne hors matching."""
    if not isinstance(raw, dict) or not set(INVENTORY).issubset(raw):
        raise ValidationError(
            "Inventaire incomplet : les huit champs sont obligatoires (valeurs nulles admises)."
        )
    data = {field: raw[column] for column, field in INVENTORY.items()}
    for field in ("project_code", "source_id", "bap_status", "sage_document_number"):
        data[field] = str(data[field] or "").strip()
    data["project_code"] = data["project_code"].upper()
    if (
        not data["project_code"]
        or not data["source_id"]
        or len(data["source_id"]) > 120
        or len(data["project_code"]) > 100
    ):
        raise ValidationError("Projet ou Id invalide dans l'inventaire")
    try:
        year = Decimal(str(data["fiscal_year"]))
        if not year.is_finite() or year != int(year) or not 2000 <= year <= 2200:
            raise ValueError
        data["fiscal_year"] = int(year)
        for field in ("total_project_charges", "total_sage_charges"):
            value = data[field]
            if value is None or value == "":
                data[field] = None
            else:
                number = Decimal(str(value))
                if not number.is_finite() or abs(number) >= Decimal("1e16"):
                    raise ValueError
                data[field] = format(number.quantize(Decimal("0.01")), "f")
        if data["accounting_date"]:
            from datetime import date

            data["accounting_date"] = date.fromisoformat(
                str(data["accounting_date"])[:10]
            ).isoformat()
        else:
            data["accounting_date"] = None
    except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        raise ValidationError("Année, montant ou date invalide dans l'inventaire") from exc
    return data


def inventory_key(data):
    return build_business_key(data["project_code"], data["source_id"], data["fiscal_year"])


def insert_inventory(campaign, rows):
    keys = [inventory_key(data) for data in rows]
    previous = {}
    if campaign.previous_id:
        previous = {
            row.business_key: row
            for row in CampaignInventory.objects.filter(
                campaign_id=campaign.previous_id, business_key__in=keys
            )
        }
    records = []
    for data, key in zip(rows, keys, strict=True):
        old = previous.get(key)
        differences = {
            name: {"before": old.data.get(name), "after": value}
            for name, value in data.items()
            if old and old.data.get(name) != value
        }
        change = (
            "NEW"
            if old is None
            else "RETURNED"
            if not old.present
            else "CHANGED"
            if differences
            else "UNCHANGED"
        )
        records.append(
            CampaignInventory(
                campaign=campaign,
                business_key=key,
                project_code=data["project_code"],
                source_id=data["source_id"],
                fiscal_year=data["fiscal_year"],
                data=data,
                change=change,
                differences=differences,
            )
        )
    try:
        with transaction.atomic():
            CampaignInventory.objects.bulk_create(records, batch_size=BATCH_SIZE)
    except IntegrityError as exc:
        raise ValidationError("Identifiant Atlas répété dans l'inventaire") from exc


def group_snapshot(group):
    return json_data(
        {
            "key": group.key,
            "rule": group.rule,
            "match_status": group.match_status,
            "sage_total": group.sage_total,
            "evidence": group.evidence,
        }
    )


def source_record(line):
    data = {
        field.name: getattr(line.transaction, field.name)
        for field in line.transaction._meta.fields
        if not field.is_relation
    }
    data["project_code"] = line.transaction.project.code
    data = {
        key: format(value, ".2f") if isinstance(value, Decimal) else value
        for key, value in data.items()
    }
    return json_data(data)


def decision_record(line):
    return json_data(
        {
            "state": line.state,
            "values": line.values,
            "comment": line.comment,
            "version": line.version,
            "source_signature": line.source_signature,
            "current": is_current(line),
            "effective": effective(line),
            "actor": str(line.updated_by) if line.updated_by_id else "",
            "updated_at": line.updated_at,
            "validated_at": line.validated_at,
            "origin_id": line.validation_origin_id,
            "origin_name": line.validation_origin.name if line.validation_origin_id else "",
        }
    )


def save_decision_snapshot(line):
    if line.campaign_id:
        CampaignReview.objects.filter(campaign_id=line.campaign_id, line=line).update(
            decision=decision_record(line)
        )


def archive_legacy(scope):
    """Préserve l'état existant, sans inventer l'inventaire complet des anciens fichiers."""
    if not LineReview.objects.exists():
        return None
    campaign = Campaign.objects.create(
        name="État antérieur à la gestion des campagnes",
        scope=scope,
        inventory_complete=False,
        is_current=True,
    )
    from itertools import groupby

    lines = LineReview.objects.select_related(
        "transaction__project", "group", "updated_by"
    ).order_by("group_id", "pk")
    for _, entries in groupby(lines.iterator(chunk_size=500), key=lambda line: line.group_id):
        members = list(entries)
        current = {line.pk: is_current(line) for line in members}
        group = members[0].group
        group.context_signature = digest(
            sorted(
                [source_snapshot(line)["atlas"] for line in members],
                key=lambda item: json.dumps(item, sort_keys=True),
            )
        )
        group.save(update_fields=["context_signature"])
        frozen = CampaignGroup.objects.create(
            campaign=campaign, key=group.key, data=group_snapshot(group)
        )
        for line in members:
            line.group = group
            line.campaign = campaign
            if current[line.pk]:
                line.source_signature = signature(line)
            if line.state == "VALIDATED":
                line.validated_at = line.validated_at or line.updated_at
                line.validation_origin = campaign
            line.save(
                update_fields=["campaign", "validated_at", "validation_origin", "source_signature"]
            )
            CampaignReview.objects.create(
                campaign=campaign,
                line=line,
                group=frozen,
                project=line.transaction.project,
                source=source_record(line),
                decision=decision_record(line),
                fingerprint=signature(line),
            )
    ReviewEvent.objects.filter(campaign__isnull=True).update(campaign=campaign)
    return campaign


def add_absences(campaign):
    if not campaign.previous_id or not campaign.previous.inventory_complete:
        return
    current_keys = campaign.inventory.filter(present=True).values("business_key")
    missing = CampaignInventory.objects.filter(campaign_id=campaign.previous_id).exclude(
        business_key__in=Subquery(current_keys)
    )
    batch = []
    for old in missing.iterator(chunk_size=BATCH_SIZE):
        batch.append(
            CampaignInventory(
                campaign=campaign,
                business_key=old.business_key,
                project_code=old.project_code,
                source_id=old.source_id,
                fiscal_year=old.fiscal_year,
                data=old.data,
                present=False,
                change="ABSENT",
            )
        )
        if len(batch) == BATCH_SIZE:
            CampaignInventory.objects.bulk_create(batch, batch_size=BATCH_SIZE)
            batch = []
    if batch:
        CampaignInventory.objects.bulk_create(batch, batch_size=BATCH_SIZE)


def import_campaign(header, stream, *, job=None):
    """Appelé dans la transaction import_bundle ; aucun état partiel n'est publié."""
    from .review_import import upsert_group

    if header.get("schema_version") != 2:
        raise ValidationError("Version de campagne non prise en charge")
    name, scope = header.get("name"), header.get("scope")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 200
        or not isinstance(scope, str)
        or not scope.strip()
        or len(scope) > 200
    ):
        raise ValidationError("Nom et périmètre de campagne requis (200 caractères maximum)")
    previous = Campaign.objects.select_for_update().filter(is_current=True).first()
    if previous and previous.scope != scope:
        raise ValidationError(
            "Périmètre différent : fournissez une extraction cumulative du même périmètre."
        )
    if previous is None:
        previous = archive_legacy(scope)
    campaign = Campaign.objects.create(
        name=name.strip(),
        scope=scope,
        metadata=header,
        previous=previous,
        job=job,
        file_hash=job.file_hash if job else "",
    )
    count, inventory_count, complete, proposals_started = 0, 0, False, False
    batch, seen, group_keys = [], set(), set()
    for number, text in enumerate(stream, 2):
        if complete:
            raise ValidationError("Données après la fin du fichier")
        payload = json.loads(text)
        if "complete" in payload:
            if batch:
                insert_inventory(campaign, batch)
                batch = []
            if payload["complete"] != count or payload.get("inventory_count") != inventory_count:
                raise ValidationError("Compteurs de campagne incohérents")
            complete = True
        elif payload.get("type") == "inventory" and not proposals_started:
            batch.append(normalize_inventory(payload.get("atlas")))
            inventory_count += 1
            if len(batch) == BATCH_SIZE:
                insert_inventory(campaign, batch)
                batch = []
        elif payload.get("type") == "proposal":
            if payload.get("schema_version") != 2:
                raise ValidationError("Une proposition de campagne doit utiliser le schéma v2")
            if batch:
                insert_inventory(campaign, batch)
                batch = []
            proposals_started = True
            if payload.get("key") in group_keys:
                raise ValidationError("Groupe répété dans la campagne")
            group_keys.add(payload.get("key"))
            # Concordance inventaire / proposition, avant mutation de la projection de travail.
            parsed = [
                normalize_inventory({column: raw.get(column) for column in INVENTORY})
                for raw in payload.get("atlas", [])
            ]
            existing = {
                row.business_key: row.data
                for row in campaign.inventory.filter(
                    business_key__in=[inventory_key(data) for data in parsed]
                )
            }
            for data in parsed:
                if existing.get(inventory_key(data)) != data or data["bap_status"] != "Envoyé SAGE":
                    raise ValidationError(
                        "Proposition absente de l'inventaire ou contradictoire avec celui-ci"
                    )
            group, lines = upsert_group(payload, number, seen)
            # Tous les membres participent au contexte : une modification chez un voisin
            # invalide aussi une ancienne allocation pourtant inchangée sur cette ligne.
            members = [source_snapshot(line)["atlas"] for line in lines]
            group.context_signature = digest(
                sorted(members, key=lambda item: json.dumps(item, sort_keys=True))
            )
            group.version += (
                1  # Une page ouverte avant l'import ne décide pas dans la nouvelle campagne.
            )
            group.save(update_fields=["context_signature", "version"])
            frozen_group = CampaignGroup.objects.create(
                campaign=campaign, key=group.key, data=group_snapshot(group)
            )
            previous_reviews = (
                {
                    row.line_id: row
                    for row in CampaignReview.objects.filter(
                        campaign=previous, line_id__in=[line.pk for line in lines]
                    )
                }
                if previous
                else {}
            )
            for line in lines:
                line.campaign = campaign
                line.group = group
                old = previous_reviews.get(line.pk)
                fingerprint = signature(line)
                unchanged = bool(old and old.fingerprint == fingerprint)
                comparison = "UNCHANGED" if unchanged else "CHANGED" if old else "NEW"
                reasons = []
                if old and not unchanged:
                    current_source = source_record(line)
                    for field, label in {
                        **LABELS,
                        "atlas_label": "Libellé Atlas",
                        "sage_bap_number": "BAP SAGE",
                        "sage_third_party_code": "Code tiers SAGE",
                    }.items():
                        if old.source.get(field) != current_source.get(field):
                            reasons.append(
                                f"{label} : {old.source.get(field) or '—'}"
                                f" → {current_source.get(field) or '—'}"
                            )
                    if not reasons:
                        reasons.append(
                            "Proposition, preuves ou composition / montants du groupe modifiés"
                        )
                if old and unchanged and old.decision.get("current") and line.state == "VALIDATED":
                    line.source_signature = fingerprint
                    comparison = "CARRIED"
                elif line.version and not unchanged:
                    # Même un retour à une ancienne signature ne réactive pas une validation.
                    line.source_signature = ""
                line.save(update_fields=["campaign", "source_signature"])
                decision = decision_record(line)
                if comparison == "CARRIED":
                    decision["actor"] = old.decision.get("actor", decision["actor"])
                CampaignReview.objects.create(
                    campaign=campaign,
                    line=line,
                    group=frozen_group,
                    project=line.transaction.project,
                    source=source_record(line),
                    decision=decision,
                    comparison=comparison,
                    reasons=reasons,
                    fingerprint=fingerprint,
                )
            count += 1
        else:
            raise ValidationError("Ordre ou type d'enregistrement de campagne invalide")
    if not complete:
        raise ValidationError("Campagne interrompue : marqueur de fin absent")
    expected_reviews = campaign.inventory.filter(
        present=True, data__bap_status="Envoyé SAGE"
    ).count()
    if expected_reviews != len(seen):
        raise ValidationError("Des lignes Envoyé SAGE de l'inventaire n'ont pas de proposition")
    add_absences(campaign)
    if previous:
        previous.is_current = False
        previous.save(update_fields=["is_current"])
    campaign.is_current = True
    campaign.save(update_fields=["is_current"])
    return count
