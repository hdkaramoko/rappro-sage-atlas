# Rapprochement Atlas / Sage X3

Moteur Python de lecture, normalisation et rapprochement des extractions Atlas
et Sage X3. Il traite les lignes Atlas « Envoyé SAGE » par une cascade explicable :
preuve déjà présente, clé exacte, montant, fuzzy RapidFuzz puis clé sans libellé.
Les sources restent intactes ; les règles expérimentales nécessitent une revue
par défaut. Les ambiguïtés et les provenances sont conservées dans le résultat.

```powershell
uv sync
uv run pytest
uv run python -m reconciliation.main --atlas "data/JDD.xlsx" --sage "data/LISTPJT4.csv"
```

La CLI affiche une synthèse ; l'API Python retourne les résultats détaillés.
Voir [la documentation d'implémentation](docs/implementation.md#étape-3--moteur-de-rapprochement)
pour les règles, les options, le schéma de sortie et l'intégration UiPath.
