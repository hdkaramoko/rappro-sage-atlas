# Rapprochement Atlas / Sage X3

Moteur Python de lecture, normalisation et rapprochement des extractions Atlas
et Sage X3. Il traite les lignes Atlas « Envoyé SAGE » par une cascade explicable :
preuve déjà présente, clé exacte, montant, fuzzy RapidFuzz puis clé sans libellé.
Les sources restent intactes ; les règles expérimentales nécessitent une revue
par défaut. Les ambiguïtés et les provenances sont conservées dans le résultat.

Pour comprendre l'ordre des contrôles et interpréter les résultats, consulter
[le guide des contrôles et statuts](docs/controles_et_statuts.md).

```powershell
uv sync
uv run pytest
uv run python -m reconciliation.main --atlas "data/JDD.xlsx" --sage "data/LISTPJT4.csv"
uv run python -m reconciliation.main --atlas "data/JDD.xlsx" --sage "data/LISTPJT4.csv" --output "output/rapprochement.xlsx"
```

La CLI affiche une synthèse ; l'API Python retourne les résultats détaillés.
Avec `--output`, elle produit un classeur avec les feuilles `Résultats`, `Tentatives`
et `Synthèse`. Les 19 champs Atlas sont restitués dans l'ordre métier, suivis du
rapprochement. Toutes les lignes Atlas sont conservées, y compris hors périmètre.
Les tentatives sont écrites progressivement dans un fichier `.tentatives.jsonl`
adjacent, en mode compact par défaut (`--trace-mode detailed` pour le détail).
Le moteur préfiltre désormais Sage sur les blocs projet/tiers/BAP recherchés par
Atlas avant agrégation, en conservant les positions et identifiants Sage d'origine.
L'option `--review-output "output/propositions.jsonl"` produit les groupes,
les lignes Atlas et leurs preuves Sage pour l'application de validation métier.
Dans `app-suivi-reconciliation`, la commande
`uv run python manage.py import_review_bundle "../scriptsRappro/output/propositions.jsonl"`
charge ces propositions dans le nouveau parcours **Validation métier**.
Voir [le guide de restitution](docs/export_excel.md) pour l'API et les journaux.
Pour voir un exemple fictif : `uv run python -m examples.demo_export` crée
`data/exemple_rapprochement.xlsx`.
Voir [la documentation d'implémentation](docs/implementation.md#étape-3--moteur-de-rapprochement)
pour les règles, les options, le schéma de sortie et l'intégration UiPath.

Voir aussi [l'analyse des extractions réelles](docs/analyse_extractions.md) pour
les volumes observés, les tests représentatifs et les optimisations mesurées.
