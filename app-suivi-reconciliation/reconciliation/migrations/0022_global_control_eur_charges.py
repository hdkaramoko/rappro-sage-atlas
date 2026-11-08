"""Retire le seul veto de devise d'origine dans le diagnostic courant actif."""

import copy
import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.db import migrations
from django.utils import timezone

OBSOLETE_REASON = "Devise Atlas non EUR à confirmer"


def monetary_state(previous, reasons, gap, tolerance):
    """Dérive l'état du diagnostic déjà chiffré, sans recalculer les montants.

    Les exclusions, autres motifs et montants absents restent bloquants. Retourne
    EXCLU, INDETERMINE, EQUILIBRE ou ECART ; aucun choix d'écriture ni validation.
    """
    if previous == "EXCLU":
        return previous
    if reasons:
        return "INDETERMINE"
    try:
        amount, limit = Decimal(str(gap)), Decimal(str(tolerance))
        if not amount.is_finite() or not limit.is_finite() or limit < 0:
            return "INDETERMINE"
    except (InvalidOperation, ValueError, TypeError):
        return "INDETERMINE"
    return "EQUILIBRE" if abs(amount) <= limit else "ECART"


def normalize_current(data):
    """Retourne une copie nettoyée du seul motif obsolète, ou None si non concernée.

    Conserve tous les montants, affectations, motifs restants et auto_validated.
    L'état courant et le sous-état Comptabilisé suivent leurs écarts respectifs.
    La signature du résultat modifié est recalculée ; le diagnostic initial ne
    doit jamais être remplacé par cette copie. Fonction pure et idempotente.
    """
    if OBSOLETE_REASON not in data.get("reasons", []):
        return None
    result = copy.deepcopy(data)
    result["reasons"] = [reason for reason in result["reasons"] if reason != OBSOLETE_REASON]
    result["accounted_reasons"] = [reason for reason in result.get("accounted_reasons", []) if reason != OBSOLETE_REASON]
    tolerance = result.get("tolerance", "0.01")
    result["state"] = monetary_state(result.get("state"), result["reasons"], result.get("gap"), tolerance)
    result["accounted_state"] = monetary_state(result.get("accounted_state"), result["accounted_reasons"],
                                               result.get("accounted_gap"), tolerance)
    result.pop("signature", None)
    result["signature"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False,
                                                    allow_nan=False).encode()).hexdigest()
    return result


def correct_active_diagnostics(apps, schema_editor):
    """Actualise les diagnostics actifs concernés par lots, sans rejouer de décision.

    Les modèles historiques garantissent la reproductibilité. L'initial data/state,
    les sources, les campagnes closes et has_pending restent intacts. Seuls le
    résultat courant, son état indexé, sa version et sa date sont actualisés.
    La migration atomique verrouille d'abord la campagne comme les décisions.
    Aucun moteur, import ou autorisation AUTO n'est déclenché.
    """
    Control = apps.get_model("reconciliation", "CampaignGlobalControl")
    Campaign = apps.get_model("reconciliation", "Campaign")
    alias = schema_editor.connection.alias
    # Même ordre de verrouillage que les services de décision : campagne d'abord.
    active_ids = list(Campaign.objects.using(alias).select_for_update().filter(is_current=True,
        published=True).order_by("pk").values_list("pk", flat=True))
    rows = Control.objects.using(alias).filter(campaign_id__in=active_ids,
        current_state="INDETERMINE").order_by("pk")
    last_pk, updated = 0, timezone.now()
    # Pagination par clé primaire : modifier l'état indexé ne doit pas déplacer
    # les lignes devant un curseur encore ouvert sur cet index, notamment SQLite.
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
            Control.objects.using(alias).bulk_update(batch, ["current_data", "current_state", "current_version", "current_updated_at"], batch_size=250)


class Migration(migrations.Migration):
    """Corrige le diagnostic actif uniquement ; le retour arrière ne réintroduit pas le veto."""
    dependencies = [("reconciliation", "0021_control_workspace_indexes")]
    operations = [migrations.RunPython(correct_active_diagnostics, migrations.RunPython.noop)]
