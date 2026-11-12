"""Contrôle ciblé de la tolérance monétaire des affectations individuellement prouvées."""

from reconciliation_contract import control_identity, entry_from_sage
from reconciliation_contract.sage_inventory import consolidate, inventory_record, exclusion_policy


def test_tolerance_requires_server_attestation_and_preserves_uniqueness():
    """La preuve unique attestée admet un centime, sans ouvrir la tolérance aux anciennes allocations."""
    raw = {"Projet": "P", "Numéro pièce": "D", "Date comptable": "2026-01-01", "Journal": "ACH",
           "N° de ligne comptable": "1", "N° de ligne Analytique": "1", "Charges (Dépenses)": "100",
           "Code Tiers - Tiers doc Orig": "T", "Libellé pièce": "Mission", "Devise": "EUR"}
    entry = entry_from_sage(raw)
    records = [inventory_record(entry, exclusion_policy())]
    allocation = {"line_key": "A", "amount": "100.01", "refs": [entry["ref"]], "validated": True,
                  "current": True, "source_status": "Envoyé SAGE"}
    identity = control_identity(entry, sage=True)
    assert consolidate(identity, [], records, [allocation])["state"] == "INDETERMINE"
    allocation["individual_tolerance_verified"] = True
    assert consolidate(identity, [], records, [allocation])["state"] == "EQUILIBRE"
    assert consolidate(identity, [], records, [allocation, allocation])["state"] == "INDETERMINE"
