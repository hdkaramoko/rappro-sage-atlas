"""Contrat informatif des historiques BAP, indépendant des preuves de matching."""

from datetime import datetime
import re
import unicodedata

POLICY = "bap-history-v1"
FIELDS = ("bap_created_at", "bap_created_by", "bap_modified_at", "bap_modified_by")


def bap_key(value):
    """Retourne une référence BAP technique sans espaces, ou vide si invalide.

    Normalise Unicode et casse sans modifier les numéros sources. Les numéros
    attendus commencent par BAP et comportent au plus 100 caractères.
    """
    if not isinstance(value, str):
        return ""
    value = "".join(unicodedata.normalize("NFKC", value).split()).upper()
    return value if len(value) <= 100 and re.fullmatch(r"BAP[A-Z0-9_/-]+", value) else ""


def validate_record(record):
    """Valide un contexte unique projet/BAP et retourne le dictionnaire inchangé.

    Les dates ISO restent textuelles pour préserver l'absence de fuseau ; les
    absences sont nulles. ValueError refuse types, longueurs ou clés incohérents.
    Aucun champ ne participe aux signatures métier ni aux calculs comptables.
    """
    if not isinstance(record, dict) or set(record) != {"project_code", "bap_sage_number", *FIELDS}:
        raise ValueError("Historique BAP : structure invalide")
    code, bap = record["project_code"], record["bap_sage_number"]
    if not isinstance(code, str) or not code or len(code) > 100 or code != code.strip().upper() or not bap or bap_key(bap) != bap:
        raise ValueError("Historique BAP : projet ou référence invalide")
    for key in FIELDS:
        value = record[key]
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > (40 if key.endswith("_at") else 255):
            raise ValueError("Historique BAP : valeur invalide")
        if key.endswith("_at"):
            try:
                if "T" not in value:
                    raise ValueError()
                datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("Historique BAP : date ISO invalide") from exc
    return record
