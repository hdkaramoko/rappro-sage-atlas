# Import PostgreSQL : champs budgétaires longs

Le fichier `data/outputs/campagne_04112026.jsonl` contient, dans les propositions,
55 libellés de ligne budgétaire de plus de 255 caractères (maximum 753) et
deux codes de plus de 100 caractères (maximum 142). Le premier dépassement
concerne l'Id Atlas `1593420`, ligne JSONL 830798 : libellé de 397 caractères.
PostgreSQL refuse ces valeurs ; SQLite ne faisait pas respecter les limites VARCHAR.

## Modification

`ReconciliationTransaction.budget_line_code` passe de VARCHAR(100) à VARCHAR(255).
`budget_line_label` devient un champ SQL TEXT : aucune limite arbitraire n'est
ajoutée aux libellés descriptifs. Les textes et accents sont conservés, sans
troncature ni modification du JSONL. Le contrat, le matching et les décisions
métier restent identiques.

Fichiers :

* `reconciliation/models.py` : nouveaux types/limites et docstring du modèle.
* `reconciliation/migrations/0019_widen_budget_line_fields.py` : altérations SQL,
  restauration des triggers de révision si SQLite reconstruit la table.
* `reconciliation/test_budget_line_import.py` : import d'un code de 142 caractères
  et d'un libellé accentué de 753 caractères, absence de troncature, historique
  préservé et révision SQLite toujours active après migration.

Les chemins ci-dessus sont relatifs à `app-suivi-reconciliation`.

## Vérifications

Depuis l'application :
`../.venv/Scripts/python.exe manage.py test reconciliation.test_budget_line_import reconciliation.test_migrations imports_app.test_sqlite_staging --noinput --verbosity 0`
→ **4 tests, OK**, incluant les scénarios isolés de staging SQLite sur disque.
Les bases de test neuves appliquent la migration 0019 ; le test de migrations
vérifie également le retour depuis le schéma initial jusqu'au schéma courant.

`makemigrations --check --dry-run` ne détecte aucun écart et `git diff --check`
ne détecte aucune erreur d'espaces. Aucun test sur une instance PostgreSQL dédiée
n'a été exécuté : les vérifications utilisent les bases SQLite jetables et la
validation Django des longueurs de champs.

## Déploiement

Déployer l'application corrigée, puis exécuter depuis son environnement :

```sh
python manage.py migrate
```

Relancer ensuite l'import du **même JSONL**. Sa régénération n'est pas nécessaire.
La base applicative existante n'a pas été migrée pendant le développement :
les migrations sont vérifiées uniquement sur les bases de test jetables.

Un retour au schéma antérieur après import des textes longs risquerait de perdre
des données ou d'échouer sur PostgreSQL. Conserver les colonnes élargies lors
d'un retour de code, ou examiner/sauvegarder les valeurs avant tout rétrécissement.
