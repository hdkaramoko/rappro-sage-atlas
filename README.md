# Chargement Atlas / Sage X3

Premières briques du rapprochement : lecture, validation, typage, déduplication
et création de colonnes canoniques normalisées, avec conservation des sources.
Les règles métier seront développées ultérieurement.

```powershell
uv sync
uv run pytest
uv run python -m reconciliation.main --atlas "data/JDD.xlsx" --sage "data/LISTPJT4.csv"
```

Voir [la documentation d'implémentation](docs/implementation.md) pour les schémas,
les hypothèses de lecture et l'intégration UiPath.
