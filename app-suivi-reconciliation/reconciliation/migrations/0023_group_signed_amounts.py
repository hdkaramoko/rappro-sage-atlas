"""Actualise le contrôle collectif sans modifier les décisions individuelles."""

import copy
import hashlib
import json
from importlib import import_module

from django.db import migrations
from django.utils import timezone

monetary_state = import_module("reconciliation.migrations.0022_global_control_eur_charges").monetary_state
OBSOLETE_REASONS = {
    "Signes mixtes / compensation charge-avoir à examiner",
    "Signes mixtes à examiner",
    "Unicité économique ODS/ODG non démontrée",
}


def normalize_current(data):
    """Retire les trois vetos collectifs et recalcule les états sur les écarts signés.

    Les écarts consolidés étaient déjà signés. Montants, décisions, allocations,
    auto_validated et diagnostic initial restent intacts. Retourne une copie
    signée ou None si non concernée ; traitement pur et idempotent.
    """
    if not OBSOLETE_REASONS.intersection(data.get("reasons", []) + data.get("accounted_reasons", [])):
        return None
    result = copy.deepcopy(data)
    for field in ("reasons", "accounted_reasons"):
        result[field] = [reason for reason in result.get(field, []) if reason not in OBSOLETE_REASONS]
    tolerance = result.get("tolerance", "0.01")
    result["state"] = monetary_state(result.get("state"), result["reasons"], result.get("gap"), tolerance)
    result["accounted_state"] = monetary_state(result.get("accounted_state"), result["accounted_reasons"],
                                               result.get("accounted_gap"), tolerance)
    result.pop("signature", None)
    result["signature"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False,
                                                    allow_nan=False).encode()).hexdigest()
    return result


def correct_active_diagnostics(apps, schema_editor):
    """Corrige par lots les résultats actifs publiés, sous verrou de campagne.

    Ne change ni données initiales, ni décisions, ni campagnes historiques.
    La version courante avance pour empêcher une décision sur une vue périmée.
    Aucun import ni moteur d'auto-validation individuelle n'est déclenché.
    """
    Campaign = apps.get_model("reconciliation", "Campaign")
    Control = apps.get_model("reconciliation", "CampaignGlobalControl")
    alias = schema_editor.connection.alias
    active_ids = list(Campaign.objects.using(alias).select_for_update().filter(is_current=True,
        published=True).order_by("pk").values_list("pk", flat=True))
    rows = Control.objects.using(alias).filter(campaign_id__in=active_ids,
        current_state="INDETERMINE").order_by("pk")
    last_pk, updated = 0, timezone.now()
    while page := list(rows.filter(pk__gt=last_pk)[:250]):
        last_pk, batch = page[-1].pk, []
        for row in page:
            result = normalize_current(row.current_data or row.data)
            if result is None:
                continue
            row.current_data, row.current_state = result, result["state"]
            row.current_version += 1
            row.current_updated_at = updated
            batch.append(row)
        if batch:
            Control.objects.using(alias).bulk_update(batch,
                ["current_data", "current_state", "current_version", "current_updated_at"], batch_size=250)


class Migration(migrations.Migration):
    """Actualise les résultats courants ; le retour arrière conserve leur diagnostic."""

    dependencies = [("reconciliation", "0022_global_control_eur_charges")]
    operations = [migrations.RunPython(correct_active_diagnostics, migrations.RunPython.noop)]
