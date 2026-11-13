# Rapprochement Atlas / Sage X3

Le [Pôle Atlas](docs/poles_atlas.md) complète le Département : configuration des
pôles suivis, classification Hors DP et filtres historisés. Les 12 pôles métier
validés sont renseignés dans `POLES_SUIVIS`.

L'[enrichissement des départements](docs/enrichissement_departements_projets_atlas.md)
ajoute deux référentiels Excel configurables, deux inventaires de projets et le
filtre Département transcodifié, sans changer les règles de rapprochement.

Le [volet A BAP / tolérance](docs/volet_a_bap_tolerance.md) décrit l'affichage des
références, l'ordre des règles et les seuls seuils résiduels portés à 0,05 €.

Moteur Python de lecture, normalisation et rapprochement des extractions Atlas
et Sage X3. Il traite les lignes Atlas « Envoyé SAGE » par une cascade explicable :
preuve déjà présente, clé exacte, montant, fuzzy RapidFuzz, clé sans libellé,
puis recours par BAP et écritures individuelles pour les lignes restantes.
Les sources restent intactes ; les règles expérimentales nécessitent une revue
par défaut. Les ambiguïtés et les provenances sont conservées dans le résultat.

Voir le [lot sélection Sage, AUTO sans libellé et recours BAP/individuel](docs/matching_bap_individuel_decision.md)
pour les conditions d'AUTO, les tests et la recette d'une nouvelle campagne.

Pour comprendre l'ordre des contrôles et interpréter les résultats, consulter
[le guide des contrôles et statuts](docs/controles_et_statuts.md).

```powershell
uv sync
uv run pytest
uv run python -m reconciliation.main --atlas "data/JDD.xlsx" --sage "data/LISTPJT4.csv"
uv run python -m reconciliation.main --atlas "data/JDD.xlsx" --sage "data/LISTPJT4.csv" --output "output/rapprochement.xlsx"
uv run python -m reconciliation.main --atlas "data/inputs/JDD.xlsx" --sage "data/inputs/ZLISTPJT.csv" --year 2026 --atlas-projects "data/inputs/ProjetAtlas.xlsx" --department-mapping "data/inputs/transcodification.xlsx" --review-output "data/outputs/campagne_ddmm2026.jsonl"
```

La CLI affiche une synthèse ; l'API Python retourne les résultats détaillés.
`--year` filtre Atlas sur `Année` et SAGE sur l'année de `Date comptable`.
Voir le [guide du filtre annuel et des portefeuilles](docs/filtre_annuel_et_portefeuilles.md).
Avec `--output`, elle produit un classeur avec les feuilles `Résultats`, `Tentatives`
et `Synthèse`. Les 19 champs Atlas sont restitués dans l'ordre métier, suivis du
rapprochement. Toutes les lignes Atlas sont conservées, y compris hors périmètre.
Les tentatives sont écrites progressivement dans un fichier `.tentatives.jsonl`
adjacent, en mode compact par défaut (`--trace-mode detailed` pour le détail).
Le moteur préfiltre désormais Sage sur les blocs projet/tiers/BAP recherchés par
Atlas avant agrégation, en conservant les positions et identifiants Sage d'origine.
L'option `--review-output "output/propositions.jsonl"` produit une campagne JSONL v2 :
inventaire Atlas complet, groupes, lignes Atlas rapprochées et preuves SAGE.
`--campaign-name "Septembre 2026"` nomme la campagne ; `--campaign-scope "atlas-complet"`
identifie le périmètre cumulatif stable. Voir le [guide des campagnes](docs/campagnes_rapprochement.md)
pour la comparaison, les absences, le report des validations et les limites de volumétrie.
Dans `app-suivi-reconciliation`, la commande
`uv run python manage.py import_review_bundle "../output/propositions.jsonl"`
charge ces propositions dans le nouveau parcours **Validation métier**.
Voir [le guide de restitution](docs/export_excel.md) pour l'API et les journaux.
Pour voir un exemple fictif : `uv run python -m examples.demo_export` crée
`data/exemple_rapprochement.xlsx`.
Voir [la documentation d'implémentation](docs/implementation.md#étape-3--moteur-de-rapprochement)
pour les règles, les options, le schéma de sortie et l'intégration UiPath.

Voir aussi [l'analyse des extractions réelles](docs/analyse_extractions.md) pour
les volumes observés, les tests représentatifs et les optimisations mesurées.

## Multiples Atlas et affectations métier

La CLI produit maintenant un JSONL v3 avec les contrôles des multiples et les preuves nécessaires à la validation. Voir le [guide français](docs/multiples_atlas_affectations_export.md) : politique de montants explicite, migration Django, usage, exports et limites.

## Mode maintenance de l’application Django

Voir le [guide d’administration et de récupération](docs/mode_maintenance_django.md)
pour programmer, activer et désactiver la maintenance, les permissions et la migration.
