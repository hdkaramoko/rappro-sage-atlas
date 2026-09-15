"""Jeux synthétiques partageant les vrais noms de colonnes sources."""

import pandas as pd

from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage


def atlas_row(**changes):
    return {"Id": "001", "Code projet": "P", "Libellé ATLAS": "FACTURE CONSULTANT DUPONT JANVIER",
            "Code tiers SAGE": "T", "N° BAP (SAGE)": "B", "Statut BAP": "Envoyé SAGE",
            "Total charges projet (€)": 1000.0, **changes}


def sage_row(**changes):
    return {"Projet": "P", "Libellé pièce": "FACTURE CONSULTANT DUPONT JANVIER",
            "Code Tiers - Tiers doc Orig": "T", "Référence": "B", "Charges (Dépenses)": 1000.0,
            "Numéro pièce": "DOC-01", "Date comptable": pd.Timestamp("2026-01-31"), **changes}


def frames(atlas=None, sage=None):
    return (transform_atlas(pd.DataFrame([atlas_row()] if atlas is None else atlas)),
            transform_sage(pd.DataFrame([sage_row()] if sage is None else sage)))
