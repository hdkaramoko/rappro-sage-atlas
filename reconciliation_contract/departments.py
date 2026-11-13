"""Validation commune du contexte organisationnel, indépendant du matching."""

import unicodedata

POLICY = "project-departments-v1"
POLE_POLICY = "project-poles-v1"
POLE_DEFAULT = "Hors DP"


def pole_key(value):
    """Normalise Unicode, casse et espaces pour comparer, sans changer le libellé conservé."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def validate_pole_configuration(configuration):
    """Valide une photographie de configuration et retourne son index de libellés.

    Exige une liste explicite, éventuellement vide, et le repli Hors DP. Refuse
    noms vides, trop longs ou ambigus ; ValueError demande une correction. Les
    dénominations suivies sont conservées exactement ; aucune écriture.
    """
    if not isinstance(configuration, dict) or set(configuration) != {"followed", "fallback"}:
        raise ValueError("Configuration des pôles absente ou invalide : compléter POLES_SUIVIS dans reconciliation/config.py")
    followed = configuration["followed"]
    if not isinstance(followed, (list, tuple)) or configuration["fallback"] != POLE_DEFAULT:
        raise ValueError("POLES_SUIVIS doit être une liste explicite ; POLE_PAR_DEFAUT doit être Hors DP")
    index = {}
    for value in followed:
        if not isinstance(value, str) or not value.strip() or len(value) > 255 or value != value.strip():
            raise ValueError("Libellé de pôle suivi vide ou invalide")
        key = pole_key(value)
        if key in index or key == pole_key(POLE_DEFAULT):
            raise ValueError("Pôles suivis répétés, ambigus ou confondus avec Hors DP")
        index[key] = value
    return index


def classified_pole(source, index):
    """Retourne le nom suivi exact ou Hors DP pour une source textuelle, sans mutation."""
    return index.get(pole_key(source), POLE_DEFAULT)


def validate_departments(header):
    """Retourne les rattachements validés d'un en-tête, ou {} pour un ancien flux.

    Exige une politique connue et des codes uniques normalisés, des libellés
    source/consolidé cohérents et un indicateur booléen de présence. Lève
    ValueError sur contradiction ; ne modifie ni en-tête ni données métier.
    La politique pôle optionnelle impose les deux champs source/classification
    et sa configuration figée ; un ancien flux sans pôle reste inchangé.
    """
    policy = header.get("department_policy")
    rows = header.get("project_departments")
    pole_policy = header.get("pole_policy")
    pole_configuration = header.get("pole_configuration")
    poles = pole_policy is not None or pole_configuration is not None
    if poles and (pole_policy != POLE_POLICY or policy != POLICY):
        raise ValueError("Politique de pôle invalide ou non prise en charge")
    index = validate_pole_configuration(pole_configuration) if poles else None
    if policy is None and rows is None:
        return {}
    if policy != POLICY or header.get("schema_version") != 3 or not isinstance(rows, dict):
        raise ValueError("Contrat des départements invalide ou non pris en charge")
    for code, row in rows.items():
        if not isinstance(code, str) or not code or len(code) > 100 or code != code.strip().upper():
            raise ValueError("Code projet du référentiel départemental invalide")
        expected = {"source", "consolidated", "in_reference"} | ({"pole", "pole_source"} if poles else set())
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError(f"Rattachement départemental invalide : {code}")
        if any(not isinstance(row[key], str) or len(row[key]) > 255 or row[key] != row[key].strip()
               for key in ("source", "consolidated")) or type(row["in_reference"]) is not bool:
            raise ValueError(f"Valeurs départementales invalides : {code}")
        if bool(row["source"]) != bool(row["consolidated"]) or row["in_reference"] != bool(row["source"]):
            raise ValueError(f"Département absent ou contradictoire : {code}")
        if poles:
            if any(not isinstance(row[key], str) or len(row[key]) > 255 for key in ("pole", "pole_source")):
                raise ValueError(f"Pôle invalide : {code}")
            if row["pole"] != classified_pole(row["pole_source"], index) or not row["in_reference"] and row["pole_source"] != "":
                raise ValueError(f"Pôle source/classification contradictoire : {code}")
    return rows
