"""Contrat moteur : campagnes v2 et compatibilité des anciens fichiers v1."""

import json
from decimal import Decimal
from itertools import chain

from django.core.exceptions import ValidationError
from django.db import transaction

from imports_app.services import _parse_new, build_business_key
from projects.models import Project

from .models import Campaign, LineReview, ReconciliationTransaction, ReviewGroup


def upsert_group(payload, number, seen, *, projects=None):
    """Met à jour la projection de travail ; campaigns.py conserve les photographies."""
    if payload.get("schema_version") not in (1, 2, 3) or not payload.get("atlas"):
        raise ValidationError("Format de propositions invalide")
    code = payload["project"].strip().upper()
    project = projects.get(code) if projects is not None else None
    if project is None:
        project, _ = Project.objects.get_or_create(code=code, defaults={"label": "Projet importé"})
        if projects is not None:
            projects[code] = project
    group, _ = ReviewGroup.objects.select_for_update().get_or_create(
        key=payload["key"],
        defaults={
            "project": project,
            "rule": payload["rule"],
            "match_status": payload["match_status"],
        },
    )
    if group.project_id != project.pk:
        raise ValidationError("Groupe partagé entre projets")
    proposed = {
        "rule": payload["rule"],
        "match_status": payload["match_status"],
        "sage_total": Decimal(str(payload["sage_total"]))
        if payload["sage_total"] is not None
        else None,
        "evidence": payload["evidence"],
    }
    if proposed["sage_total"] is not None and not proposed["sage_total"].is_finite():
        raise ValidationError("Total SAGE non fini")
    if any(getattr(group, key) != value for key, value in proposed.items()):
        for key, value in proposed.items():
            setattr(group, key, value)
        group.version += 1
        group.save()
    lines = []
    for raw in payload["atlas"]:
        row = _parse_new(raw, number)
        if row.pop("project_code").upper() != project.code:
            raise ValidationError("Ligne Atlas hors du projet du groupe")
        key = build_business_key(project.code, row["source_id"], row["fiscal_year"])
        if key in seen:
            raise ValidationError("Ligne Atlas présente plusieurs fois dans l'import")
        seen.add(key)
        defaults = {k: v for k, v in row.items() if not k.startswith("suggestion_")}
        defaults.update(
            reference=row["source_id"],
            label=row["atlas_label"],
            atlas_status_source=row["bap_status"],
        )
        item = ReconciliationTransaction.objects.filter(
            project=project, fiscal_year=row["fiscal_year"], source_id=row["source_id"]
        ).first()
        if item is None:
            item, _ = ReconciliationTransaction.objects.update_or_create(
                business_key=key, defaults={"project": project, **defaults}
            )
        else:
            for field, value in defaults.items():
                setattr(item, field, value)
            item.save()
        line, _ = LineReview.objects.get_or_create(transaction=item, defaults={"group": group})
        if line.group_id != group.pk:
            line.group = group
            line.save(update_fields=["group"])
        line.transaction, line.group = item, group
        lines.append(line)
    return group, lines


@transaction.atomic
def import_bundle(path, *, job=None, progress=None):
    """Valide et importe atomiquement ; le worker SQLite appelle ce service sur sa copie privée."""
    import hashlib
    from pathlib import Path
    with Path(path).open("rb") as source:
        file_hash = hashlib.file_digest(source, "sha256").hexdigest()
    existing = Campaign.objects.filter(file_hash=file_hash).first()
    if existing:
        return existing.reviews.count()
    with open(path, encoding="utf-8") as stream:
        first = stream.readline()
        if not first:
            raise ValidationError("Fichier vide")
        header = json.loads(first)
        if header.get("type") == "campaign":
            from .campaigns import import_campaign

            count = import_campaign(header, stream, job=job, progress=progress)
            Campaign.objects.filter(is_current=True).update(file_hash=file_hash)
            return count
        if Campaign.objects.exists():
            raise ValidationError(
                "Une campagne avec inventaire (format v2) est requise. Relancez le moteur."
            )
        count, complete, seen = 0, False, set()
        for number, payload in enumerate(chain([header], (json.loads(text) for text in stream)), 1):
            if complete:
                raise ValidationError("Données après la fin du fichier")
            if "complete" in payload:
                if payload["complete"] != count:
                    raise ValidationError("Nombre de groupes incohérent")
                complete = True
            else:
                if payload.get("schema_version") != 1:
                    raise ValidationError(
                        "Le format v2 nécessite un en-tête de campagne et un inventaire."
                    )
                upsert_group(payload, number, seen)
                count += 1
        if not complete:
            raise ValidationError(
                "Import interrompu : marqueur de fin absent ; aucune modification appliquée"
            )
        return count
