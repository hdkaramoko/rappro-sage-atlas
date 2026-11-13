"""Validation commune du contexte organisationnel, indépendant du matching."""

POLICY = "project-departments-v1"


def validate_departments(header):
    """Retourne les rattachements validés d'un en-tête, ou {} pour un ancien flux.

    Exige une politique connue et des codes uniques normalisés, des libellés
    source/consolidé cohérents et un indicateur booléen de présence. Lève
    ValueError sur contradiction ; ne modifie ni en-tête ni données métier.
    """
    policy = header.get("department_policy")
    rows = header.get("project_departments")
    if policy is None and rows is None:
        return {}
    if policy != POLICY or header.get("schema_version") != 3 or not isinstance(rows, dict):
        raise ValueError("Contrat des départements invalide ou non pris en charge")
    for code, row in rows.items():
        if not isinstance(code, str) or not code or len(code) > 100 or code != code.strip().upper():
            raise ValueError("Code projet du référentiel départemental invalide")
        if not isinstance(row, dict) or set(row) != {"source", "consolidated", "in_reference"}:
            raise ValueError(f"Rattachement départemental invalide : {code}")
        if any(not isinstance(row[key], str) or len(row[key]) > 255 or row[key] != row[key].strip()
               for key in ("source", "consolidated")) or type(row["in_reference"]) is not bool:
            raise ValueError(f"Valeurs départementales invalides : {code}")
        if bool(row["source"]) != bool(row["consolidated"]) or row["in_reference"] != bool(row["source"]):
            raise ValueError(f"Département absent ou contradictoire : {code}")
    return rows
