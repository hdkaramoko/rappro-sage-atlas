"""Résolution serveur de preuves importées, sans dérogation comptable implicite."""

from decimal import Decimal
from django.core.exceptions import ValidationError
from reconciliation_contract import STANDARD, digest, money
from reconciliation_contract.piece_coherence import identifier


def confirmed_manual_evidence(line, resolved):
    """Retrouve une preuve Confirmé unique dans le contrôle et l'inventaire courants.

    Seul un BAP différent est toléré, après décision humaine. Montants signés,
    projet/exercice/pièce/date/tiers et contenu inventaire doivent correspondre.
    Retourne (entrée canonique, détails d'audit) ; ValidationError si aucune preuve,
    ambiguïté ou autre anomalie. Lecture seule, aucune candidate d'écran reconstruite.
    """
    from .models import CampaignSageEntry
    from reconciliation_contract.sage_inventory import CAPABILITY
    key = digest({"strategy": STANDARD, "parts": [line.transaction.project.code,
        line.transaction.fiscal_year, identifier(resolved["document"])]})
    control = line.campaign.controls.filter(key=key, strategy=STANDARD).first()
    if not control or control.data["status"] == "UNKNOWN":
        raise ValidationError("Preuve Sage Confirmé absente ou contrôle incertain")
    if control.data.get("signature") != digest({k: v for k, v in control.data.items() if k not in ("signature", "key")}):
        raise ValidationError("Signature du contrôle Confirmé incohérente")
    amount = money(line.transaction.total_sage_charges)
    if (amount is None or money(resolved["amount"]) is None or abs(amount-money(resolved["amount"])) > Decimal("0.01")
            or identifier(resolved["document"]) != identifier(line.transaction.sage_document_number)
            or str(resolved["date"])[:10] != str(line.transaction.accounting_date)[:10]):
        raise ValidationError("Pièce/date/montant différent de la preuve Confirmé Atlas")
    matches = [e for e in control.data["entries"] if e["identity_complete"]
        and e["project_code"] == line.transaction.project.code and e["fiscal_year"] == line.transaction.fiscal_year
        and e["document"] == identifier(resolved["document"]) and e["date"] == str(resolved["date"])[:10]
        and e["third_party"] == identifier(line.transaction.sage_third_party_code)
        and money(e["amount"]) is not None and abs(money(e["amount"])-amount) <= Decimal("0.01")
        and money(e["amount"])*amount >= 0]
    if len(matches) != 1 or len({e["ref"] for e in control.data["entries"]}) != len(control.data["entries"]):
        raise ValidationError("Écriture Confirmé absente ou ambiguë : sélection manuelle requise")
    entry = matches[0]
    bap = None
    if CAPABILITY in line.campaign.metadata.get("capabilities", []):
        records = list(CampaignSageEntry.objects.filter(campaign=line.campaign, entry_ref=entry["ref"], eligible=True))
        if len(records) != 1 or records[0].data["entry"] != entry:
            raise ValidationError("Preuve Confirmé absente ou contradictoire dans l'inventaire Sage")
        from reconciliation_contract.sage_inventory import validate_inventory_record
        try:
            validate_inventory_record(records[0].data, line.campaign.metadata["sage_exclusions"])
        except ValueError as exc:
            raise ValidationError("Signature de la preuve Confirmé incohérente") from exc
        bap = records[0].data.get("attributes", {}).get("Référence", "")
    else:
        from .piece_coherence import campaign_check
        data = campaign_check(line) or {}
        evidence = [e for e in data.get("sage", []) if e["ref"] == entry["ref"]]
        if len(evidence) != 1:
            raise ValidationError("Diagnostic individuel Confirmé absent")
        bap = evidence[0]["bap"]
    return entry, {"entry_ref": entry["ref"], "atlas_bap": line.transaction.sage_bap_number,
                   "sage_bap": bap, "bap_difference": identifier(bap) != identifier(line.transaction.sage_bap_number),
                   "checks": ["projet/exercice", "pièce/date", "tiers", "montant signé", "preuve importée",
                              "réservations et capacité revérifiées par la projection transactionnelle"]}


def exact_group_signature(group):
    """Signe les preuves et la composition immuables d'un groupe Exact ; lecture pure."""
    return digest({"context": group.context_signature, "evidence": group.evidence, "total": str(group.sage_total)})


def verified_exact_group_entry(line):
    """Revalide une affectation individuelle Exact créée par la préparation bijective.

    Vérifie signature collective, appartenance aux candidats réels et montant
    individuel. Retourne l'entrée ; ValidationError interdit une attribution
    falsifiée ou périmée. La capacité est contrôlée ensuite par apply_projection.
    """
    from .multiple_review import candidates_for
    assignment = line.automatic_assignment
    entry = assignment.get("entry", {})
    if (line.group.rule != "MATCH_EXACT" or assignment.get("group_signature") != exact_group_signature(line.group)
            or candidates_for(line).get(entry.get("ref")) != entry
            or money(line.transaction.total_project_charges) is None or money(entry.get("amount")) is None
            or abs(money(line.transaction.total_project_charges)-money(entry["amount"])) > Decimal("0.01")
            or money(line.transaction.total_project_charges)*money(entry["amount"]) < 0):
        raise ValidationError("Affectation Exact collective absente ou périmée")
    return entry
