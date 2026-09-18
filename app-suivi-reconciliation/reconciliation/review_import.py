"""Import du contrat JSONL moteur ; réimport identique sans perte des décisions."""

import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from imports_app.services import _parse_new, build_business_key
from projects.models import Project

from .models import LineReview, ReconciliationTransaction, ReviewGroup


@transaction.atomic
def import_bundle(path):
    count = 0
    complete = False
    seen = set()
    with open(path, encoding="utf-8") as stream:
        for number, text in enumerate(stream, 1):
            if complete:
                raise ValidationError("Données après la fin du fichier")
            payload = json.loads(text)
            if "complete" in payload:
                if payload["complete"] != count:
                    raise ValidationError("Nombre de groupes incohérent")
                complete = True
                continue
            if payload.get("schema_version") != 1 or not payload.get("atlas"):
                raise ValidationError("Format de propositions invalide")
            project, _ = Project.objects.get_or_create(
                code=payload["project"].strip().upper(), defaults={"label": "Projet importé"}
            )
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
            if any(getattr(group, key) != value for key, value in proposed.items()):
                for key, value in proposed.items():
                    setattr(group, key, value)
                group.version += 1
                group.save()
            for raw in payload["atlas"]:
                row = _parse_new(raw, number)
                if row.pop("project_code").upper() != project.code:
                    raise ValidationError("Ligne Atlas hors du projet du groupe")
                key = build_business_key(project.code, row["source_id"], row["fiscal_year"])
                if key in seen:
                    raise ValidationError("Ligne Atlas présente plusieurs fois dans l'import")
                seen.add(key)
                # N'écrase pas les corrections de l'ancien parcours ni les décisions.
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
                line, _ = LineReview.objects.get_or_create(
                    transaction=item, defaults={"group": group}
                )
                if line.group_id != group.pk:
                    line.group = group
                    line.save(update_fields=["group"])
            count += 1
    if not complete:
        raise ValidationError(
            "Import interrompu : marqueur de fin absent ; aucune modification appliquée"
        )
    return count
