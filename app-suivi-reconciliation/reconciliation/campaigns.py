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
from reconciliation_contract.atlas_context import ATLAS_CONTEXT, context_number

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
LABELS = {value: key for key, value in {**INVENTORY, **ATLAS_CONTEXT}.items()}
BATCH_SIZE = 500


def json_data(value):
    """Convertit dates et Decimal en valeurs JSON pour une photographie portable."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False))


def digest(value):
    """Calcule une empreinte déterministe des données métier sérialisables."""
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


def normalize_inventory(raw, *, extended=False):
    """Schéma étroit : pas de création d'un objet ORM Atlas pour chaque ligne hors matching."""
    if not isinstance(raw, dict) or not set(INVENTORY).issubset(raw):
        raise ValidationError(
            "Inventaire incomplet : les huit champs sont obligatoires (valeurs nulles admises)."
        )
    data = {field: raw[column] for column, field in INVENTORY.items()}
    try:
        data.update(
            {field: context_number(raw.get(column)) for column, field in ATLAS_CONTEXT.items()}
        )
    except ValueError as exc:
        raise ValidationError(f"Contexte Atlas invalide : {exc}") from exc
    if extended:
        from reconciliation_contract import EXTRA_INVENTORY

        if not set(EXTRA_INVENTORY).issubset(raw):
            raise ValidationError("Inventaire v3 incomplet : tiers, libellé et devise requis")
        data.update({field: str(raw[column] or "") for column, field in EXTRA_INVENTORY.items()})
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
    """Construit l’identité stable projet, Id Atlas et exercice."""
    return build_business_key(data["project_code"], data["source_id"], data["fiscal_year"])


def insert_inventory(campaign, rows):
    """Insère un lot et conserve la clé de contrôle pour les recherches indexées."""
    from reconciliation_contract import control_identity
    from reconciliation_contract import digest as control_digest

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
                control_key=control_digest(control_identity(data))
                if campaign.metadata.get("schema_version") == 3
                else "",
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
    """Photographie une proposition moteur sans la décision utilisateur."""
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
    """Conserve les champs sources indépendamment de la projection courante."""
    data = {
        field.name: getattr(line.transaction, field.name)
        for field in line.transaction._meta.fields
        if not field.is_relation
    }
    data["project_code"] = line.transaction.project.code
    data = {
        key: (context_number(value) if key in ATLAS_CONTEXT.values() else format(value, ".2f"))
        if isinstance(value, Decimal)
        else value
        for key, value in data.items()
    }
    return json_data(data)


def decision_record(line):
    """Photographie décision, auteur, origine, affectation et diagnostic multiple."""
    return json_data(
        {
            "validation_source": line.validation_source,
            "auto_validation_rule": line.auto_validation_rule,
            "state": line.state,
            "values": line.values,
            "manual_assignment": line.manual_assignment,
            "automatic_assignment": line.automatic_assignment,
            "multiple_context": line.multiple_context,
            "multiple_diagnostic": line.multiple_diagnostic,
            "comment": line.comment,
            "version": line.version,
            "source_signature": line.source_signature,
            "current": is_current(line),
            "effective": effective(line),
            "actor": str(line.updated_by) if line.updated_by_id else "",
            "actor_id": line.updated_by_id,
            "updated_at": line.updated_at,
            "validated_at": line.validated_at,
            "origin_id": line.validation_origin_id,
            "origin_name": line.validation_origin.name if line.validation_origin_id else "",
        }
    )


def save_decision_snapshot(line):
    """Met à jour uniquement la photographie de la campagne de travail."""
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
    """Conserve les lignes absentes comme observations historiques non présentes."""
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


def import_campaign(header, stream, *, job=None, progress=None):
    """Appelé dans la transaction import_bundle ; aucun état partiel n'est publié."""
    from .multiple_import import import_control_batch
    from .review_import import upsert_group

    progress = progress or (lambda *args, **kwargs: None)

    if header.get("schema_version") not in (2, 3):
        raise ValidationError("Version de campagne non prise en charge")
    v3 = header["schema_version"] == 3
    piece_mode = header.get("piece_coherence_mode", "DIAGNOSTIC")
    if piece_mode not in ("DIAGNOSTIC", "ACTIVE"):
        raise ValidationError("Mode de cohérence SAGE inconnu")
    if piece_mode == "ACTIVE" and not v3:
        raise ValidationError("L'activation collective exige une campagne v3")
    if v3:
        from .multiple_import import validate_header

        validate_header(header)
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
    year = header.get("year")
    if year is not None and (type(year) is not int or not 2000 <= year <= 2200):
        raise ValidationError("Année de campagne invalide")
    active = Campaign.objects.select_for_update().filter(is_current=True).first()
    if active and active.scope != scope:
        raise ValidationError(
            "Périmètre différent : fournissez une extraction cumulative du même périmètre."
        )
    if active is None and not Campaign.objects.exists():
        active = archive_legacy(scope)
    previous = Campaign.objects.filter(scope=scope, fiscal_year=year).first()
    if previous is None and active and not active.inventory_complete:
        previous = active  # Reprise du travail antérieur, sans comparaison d'inventaires.
    campaign = Campaign.objects.create(
        name=name.strip(),
        scope=scope,
        fiscal_year=year,
        metadata=header,
        previous=previous,
        job=job,
        file_hash=job.file_hash if job else "",
    )
    count, inventory_count, complete, proposals_started = 0, 0, False, False
    controls_started, control_count = False, 0
    batch, seen, group_keys = [], set(), set()
    control_batch = []
    reviews_batch = []
    projects = {}
    for number, text in enumerate(stream, 2):
        if complete:
            raise ValidationError("Données après la fin du fichier")
        payload = json.loads(text)
        if "complete" in payload:
            if control_batch:
                import_control_batch(campaign, control_batch)
                control_batch = []
            progress("Contrôles préparés", control_count)
            if v3 and any(
                type(payload.get(k)) is not int or payload[k] < 0
                for k in ("complete", "inventory_count", "control_count")
            ):
                raise ValidationError("Compteurs v3 entiers positifs requis")
            if batch:
                insert_inventory(campaign, batch)
                batch = []
            if payload["complete"] != count or payload.get("inventory_count") != inventory_count:
                raise ValidationError("Compteurs de campagne incohérents")
            if v3 and payload.get("control_count") != control_count:
                raise ValidationError("Compteur des contrôles incohérent")
            if v3:
                from django.db.models import Count

                actual = {
                    row["status"]: row["n"]
                    for row in campaign.controls.values("status").annotate(n=Count("pk"))
                }
                if payload.get("control_statuses") != actual:
                    raise ValidationError("Compteurs de diagnostics incohérents")
            complete = True
        elif payload.get("type") == "control" and v3:
            if batch:
                insert_inventory(campaign, batch)
                batch = []
            controls_started = proposals_started = True
            control_batch.append(payload.get("data"))
            control_count += 1
            if len(control_batch) == BATCH_SIZE:
                import_control_batch(campaign, control_batch)
                control_batch = []
                progress("Contrôles préparés", control_count)
        elif payload.get("type") == "inventory" and not proposals_started:
            data = normalize_inventory(payload.get("atlas"), extended=v3)
            if year is not None and data["fiscal_year"] != year:
                raise ValidationError("L'inventaire contient une ligne hors de l'année de campagne")
            batch.append(data)
            inventory_count += 1
            if len(batch) == BATCH_SIZE:
                insert_inventory(campaign, batch)
                batch = []
                progress("Inventaire préparé", inventory_count)
        elif payload.get("type") == "proposal" and not controls_started:
            if payload.get("schema_version") != header["schema_version"]:
                raise ValidationError("Une proposition doit utiliser le schéma de sa campagne")
            if year is not None:
                from datetime import date

                for candidate in payload.get("evidence", []):
                    for row in candidate.get("rows", []):
                        try:
                            accounting_year = date.fromisoformat(
                                str(row.get("Date comptable"))[:10]
                            ).year
                        except ValueError as exc:
                            raise ValidationError(
                                "Date comptable SAGE invalide dans la campagne annuelle"
                            ) from exc
                        if accounting_year != year:
                            raise ValidationError("Preuve SAGE hors de l'année de campagne")
            if batch:
                insert_inventory(campaign, batch)
                batch = []
            proposals_started = True
            if payload.get("key") in group_keys:
                raise ValidationError("Groupe répété dans la campagne")
            group_keys.add(payload.get("key"))
            # Concordance inventaire / proposition, avant mutation de la projection de travail.
            parsed = [normalize_inventory(raw, extended=v3) for raw in payload.get("atlas", [])]
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
            group, lines = upsert_group(payload, number, seen, projects=projects)
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
            from .piece_coherence import validate_proposal_check

            diagnostic = validate_proposal_check(payload)
            frozen_group = CampaignGroup.objects.create(
                campaign=campaign, key=group.key,
                data={**group_snapshot(group), "auto_validation": payload.get("auto_validation"),
                      **({"piece_coherence": diagnostic} if diagnostic is not None else {})},
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
                line.group = group
                old = previous_reviews.get(line.pk)
                if old and line.campaign_id != previous.pk:
                    # Le retour d'un exercice/périmètre toutes années reprend sa propre
                    # photographie, pas une décision faite dans un autre contexte.
                    from django.contrib.auth import get_user_model
                    from django.utils.dateparse import parse_datetime

                    prior = old.decision
                    line.validation_source = prior.get("validation_source", "MANUAL")
                    line.auto_validation_rule = prior.get("auto_validation_rule", "")
                    line.state = prior["state"]
                    line.values = prior["values"]
                    line.manual_assignment = prior.get("manual_assignment", [])
                    line.automatic_assignment = prior.get("automatic_assignment", {})
                    line.multiple_context = prior.get("multiple_context", {})
                    line.multiple_diagnostic = prior.get("multiple_diagnostic", {})
                    line.comment = prior["comment"]
                    line.source_signature = prior["source_signature"]
                    line.validated_at = parse_datetime(prior.get("validated_at") or "")
                    line.validation_origin_id = prior.get("origin_id")
                    author = get_user_model().objects.filter(pk=prior.get("actor_id")).first()
                    if author is None and "actor_id" not in prior:
                        author = (
                            get_user_model().objects.filter(username=prior.get("actor", "")).first()
                        )
                    line.updated_by = author
                line.campaign = campaign
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
                if not v3 and line.multiple_context:
                    line.source_signature = ""
                    comparison = "CHANGED"
                    reasons.append(
                        "Fichier historique sans contrôles : validation v3 non reportable"
                    )
                line.save(
                    update_fields=[
                        "campaign",
                        "validation_source",
                        "auto_validation_rule",
                        "source_signature",
                        "state",
                        "values",
                        "manual_assignment",
                        "automatic_assignment",
                        "multiple_context",
                        "multiple_diagnostic",
                        "comment",
                        "validated_at",
                        "validation_origin",
                        "updated_by",
                    ]
                )
                decision = decision_record(line)
                if comparison == "CARRIED":
                    decision["actor"] = old.decision.get("actor", decision["actor"])
                reviews_batch.append(CampaignReview(
                    campaign=campaign,
                    line=line,
                    group=frozen_group,
                    project=line.transaction.project,
                    source=source_record(line),
                    decision=decision,
                    comparison=comparison,
                    reasons=reasons,
                    fingerprint=fingerprint,
                ))
                if len(reviews_batch) >= BATCH_SIZE:
                    CampaignReview.objects.bulk_create(reviews_batch, batch_size=BATCH_SIZE)
                    reviews_batch.clear()
            count += 1
            if count % BATCH_SIZE == 0:
                progress("Propositions préparées", count)
        else:
            raise ValidationError("Ordre ou type d'enregistrement de campagne invalide")
    if not complete:
        raise ValidationError("Campagne interrompue : marqueur de fin absent")
    if year is not None and inventory_count == 0:
        raise ValidationError("La campagne annuelle ne contient aucune ligne Atlas")
    expected_reviews = campaign.inventory.filter(
        present=True, data__bap_status="Envoyé SAGE"
    ).count()
    if expected_reviews != len(seen):
        raise ValidationError("Des lignes Envoyé SAGE de l'inventaire n'ont pas de proposition")
    if reviews_batch:
        CampaignReview.objects.bulk_create(reviews_batch, batch_size=BATCH_SIZE)
    add_absences(campaign)
    progress("Comparaison des campagnes terminée", count)
    if v3:
        from .multiple_import import finalize_controls

        finalize_controls(campaign, progress=progress)
        progress("Report des validations contrôlé", count)
    if active:
        active.is_current = False
        active.save(update_fields=["is_current"])
    campaign.is_current = True
    campaign.save(update_fields=["is_current"])
    from .auto_validation import apply_automatic_validations

    progress("Validation automatique en cours", count)
    apply_automatic_validations(campaign, progress=progress)
    progress("Publication terminée", count)
    return count
