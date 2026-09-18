# Validation des rapprochements Atlas / Sage

Application de validation par ligne Atlas des propositions du moteur de rapprochement.
Les accès reposent sur le portefeuille de projets de chaque utilisateur.

## Démarrage

Depuis `scriptsRappro/app-suivi-reconciliation` :

```powershell
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Se connecter avec un compte existant. Pour créer un administrateur :
`uv run python manage.py createsuperuser`.
Aucune donnée de démonstration n’est chargée au démarrage.

## Charger les données réelles

Le menu **Importer un rapprochement** permet aux administrateurs de transférer
le JSONL produit par le moteur indépendant, puis de suivre son chargement.
L’application ne lance pas le moteur et ne reçoit pas les extractions brutes.

Voir le [guide d’import manuel](docs/imports-rapprochements.md).

La commande ci-dessous reste disponible pour un fichier de propositions déjà généré.

Générer le fichier JSONL avec l’option `--review-output` du moteur, puis :

```powershell
uv run python manage.py import_review_bundle "../output/propositions.jsonl"
```

Attribuer les projets aux utilisateurs, puis ouvrir **Mes rapprochements**.
Le tableau de bord suit les brouillons, validations, refus et décisions à réexaminer.
L’export de conservation provient uniquement des validations métier à jour.

Voir le [guide de validation](docs/validation-metier.md).

La [note de refonte UI/UX](docs/refonte-ui-ux.md) décrit les écrans, les filtres,
les décisions et les vérifications de non-régression.

## Vérification

```powershell
uv run python manage.py test
uv run ruff check .
```
