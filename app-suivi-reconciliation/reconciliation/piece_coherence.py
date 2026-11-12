"""Diagnostic et affectations collectives vérifiées contre les contrôles SAGE."""

from django.core.exceptions import ValidationError
from reconciliation_contract.piece_coherence import atlas_entry, validate_check
from reconciliation_contract.piece_coherence import identifier
from reconciliation_contract import STANDARD, digest, money
from decimal import Decimal


def _same_atlas_entry(source: dict, diagnostic: dict) -> bool:
    """Compare deux entrées Atlas canoniques sans modifier leurs preuves signées.

    Les montants individuels EUR sont comparés en Decimal fini, exactement et
    sans tolérance : « 374 » et « 374.0 » sont égaux, deux valeurs absentes
    aussi. Une absence ne vaut jamais zéro ; un montant invalide ne correspond
    jamais. Tous les autres champs et leur présence restent strictement égaux.
    Retourne un booléen, sans effet de bord ni arrondi.
    """
    left, right = source.get("amount"), diagnostic.get("amount")
    same_amount = (left is None and right is None) or (
        money(left) is not None and money(left) == money(right)
    )
    return same_amount and (
        {key: value for key, value in source.items() if key != "amount"}
        == {key: value for key, value in diagnostic.items() if key != "amount"}
    )


def validate_proposal_check(payload):
    """Vérifie le diagnostic signé d'une proposition moteur `payload` (dict).

    Retourne le diagnostic d'origine, ou None si absent. Recalcule sa signature
    avant de vérifier l'appartenance de l'unique ligne Atlas ; seuls les formats
    textuels équivalents du montant EUR sont tolérés, via Decimal exact. Une
    différence métier, une composition invalide ou une altération lève
    ValidationError. Aucun montant, signature, fichier ou objet SQL n'est modifié.
    """
    data = payload.get("piece_coherence")
    if data is None:
        return None
    try:
        validate_check(data)
        if len(payload["atlas"]) != 1 or not any(
            _same_atlas_entry(atlas_entry(payload["atlas"][0]), row) for row in data["atlas"]
        ):
            raise ValueError("Ligne Atlas absente ou contradictoire avec le diagnostic")
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise ValidationError(f"Contrôle de cohérence SAGE invalide : {exc}") from exc
    return data


def campaign_check(line):
    frozen = line.campaign_reviews.select_related("group").filter(campaign_id=line.campaign_id).first()
    return frozen.group.data.get("piece_coherence") if frozen else None


def verified_assignment(line, resolved):
    """Une réservation automatique désigne une écriture réelle, jamais la pièce entière."""
    assignment = line.automatic_assignment
    data = campaign_check(line)
    if (not line.campaign_id or line.campaign.metadata.get("schema_version") != 3
            or line.campaign.metadata.get("piece_coherence_mode") != "ACTIVE"
            or not data or data["status"] != "PIECE_RECONCILED"
            or assignment.get("piece_signature") != data["signature"]
            or line.group.rule != "MATCH_CONFIRMED_ATLAS"):
        raise ValidationError("Autorisation collective absente ou périmée")
    entry = assignment.get("entry", {})
    key = digest({"strategy": STANDARD,
                  "parts": [data["project"], line.transaction.fiscal_year, data["document"]]})
    control = line.campaign.controls.filter(key=key, strategy=STANDARD,
        project_code=line.transaction.project.code).first()
    if not control or control.data["status"] == "UNKNOWN" or control.data["atlas"]:
        raise ValidationError("Contrôle SAGE absent, incertain ou pièce déjà comptabilisée")
    if entry not in control.data["entries"]:
        raise ValidationError("Écriture automatique absente des preuves SAGE courantes")
    actual = {r["ref"]: r for r in control.data["entries"]}
    if len(actual) != len(control.data["entries"]) or set(actual) != {r["ref"] for r in data["sage"]}:
        raise ValidationError("Périmètre SAGE du diagnostic différent du contrôle comptable")
    for row in data["sage"]:
        proof = actual[row["ref"]]
        if any(row[k] != proof[v] for k, v in (
            ("project", "project_code"), ("document", "document"), ("date", "date"),
            ("year", "fiscal_year"), ("third_party", "third_party"), ("journal", "journal"),
        )) or money(row["amount"]) != money(proof["amount"]):
            raise ValidationError("Diagnostic contradictoire avec les écritures SAGE")
    source = next((r for r in data["atlas"] if r["source_id"] == line.transaction.source_id), None)
    evidence = next((r for r in data["sage"] if r["ref"] == entry.get("ref")), None)
    if not source or not evidence or (source["third_party"], source["bap"]) != (evidence["third_party"], evidence["bap"]):
        raise ValidationError("Tiers/BAP incompatibles avec l'affectation automatique")
    if (source["third_party"] != identifier(line.transaction.sage_third_party_code)
            or source["bap"] != identifier(line.transaction.sage_bap_number)
            or source["project"] != line.transaction.project.code
            or source["year"] != line.transaction.fiscal_year
            or identifier(resolved["document"]) != entry["document"]
            or str(resolved["date"])[:10] != entry["date"]
            or money(resolved["amount"]) is None
            or abs(money(resolved["amount"]) - money(entry["amount"])) > Decimal("0.01")
            or money(resolved["amount"]) * money(entry["amount"]) < 0):
        raise ValidationError("Pièce, date ou montant incompatible avec l'écriture affectée")
    return control, entry


def compatible_piece_peer(line, other):
    """N'exempte que des Confirmé distincts d'une même preuve collective courante.

    Les affectations Exact utilisent leur propre vérification ; l'absence de
    piece_signature n'est jamais une autorisation Confirmé. Lecture sans mutation.
    """
    left, right = line.automatic_assignment, other.automatic_assignment
    if not left.get("piece_signature") or left.get("piece_signature") != right.get("piece_signature"):
        return False
    if left["entry"]["ref"] == right["entry"]["ref"]:
        return False
    try:
        verified_assignment(other, {"document": other.transaction.sage_document_number,
            "date": other.transaction.accounting_date, "amount": other.transaction.total_sage_charges})
    except ValidationError:
        return False
    return True
