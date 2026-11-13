# Validation des rapprochements Atlas / Sage

L'[ajout du Pôle](../docs/poles_atlas.md) nécessite la migration 0026 et un nouveau
JSONL enrichi. Les anciennes campagnes restent consultables avec Pôle = Hors DP.

Le [filtre Département](../docs/enrichissement_departements_projets_atlas.md)
utilise les valeurs transcodifiées historisées par campagne dans les trois vues.
Appliquer la migration `0025` puis importer un nouveau JSONL enrichi.

Voir les [correctifs tiers ODS/ODG, unicité BAP et filtres](../docs/correctifs_tiers_ods_bap_filtres.md).
Ils s'appliquent aux prochains JSONL ; aucun recalcul de la campagne courante
n'est requis. Les filtres Type de pièce et Origine sont disponibles immédiatement.

Le [cadrage exhaustif et le diagnostic ODA](../docs/cadrage_exhaustif_oda.md)
incluent toutes les écritures Sage éligibles, même sans Atlas. Pour une campagne
déjà importée, reconstruire les agrégats après essai sur copie ; aucun nouveau
JSONL ni migration n’est nécessaire pour cette évolution.

L’[import Excel des utilisateurs](../docs/import_utilisateurs_excel.md) est
accessible dans Administration → Utilisateurs. Les comptes sont créés sans
portefeuille ; leurs projets sont attribués ensuite par l’import existant.

Le [mode maintenance administrable](../docs/mode_maintenance_django.md) permet
d’avertir les utilisateurs ou de suspendre les nouveaux accès, sans supprimer
leurs sessions. Appliquer les migrations avant le déploiement.

Voir le [volet A](../docs/volet_a_bap_tolerance.md) pour les colonnes BAP,
les tableaux Atlas/Sage du contrôle et la tolérance ciblée des nouveaux JSONL.

La sélection Sage préremplit les champs de décision, recontrôlés en Decimal au
POST. Voir le [lot BAP/individuel et décision](../docs/matching_bap_individuel_decision.md)
pour les nouvelles règles, leurs garde-fous et la procédure moteur → nouvelle campagne.

Les champs Atlas **Montant refacturables**, **Prix unitaire prévu** et **Nombre
d'unités** sont affichés et comparés entre campagnes. Voir le
[guide des champs complémentaires](../docs/champs_atlas_validation.md) pour la
migration 0012 et la régénération du JSONL par le moteur.

Le bouton **Valider** confirme aussi l'affectation et les risques justifiés, sans
cases supplémentaires. Les superutilisateurs disposent du lien **Exporter la base
JSON** dans le menu latéral, avec les commentaires et l'historique des décisions.
Voir [le guide de validation et d'export](../docs/validation_simplifiee_export_json.md).

Application de validation par ligne Atlas des propositions du moteur de rapprochement.
Les accès reposent sur le portefeuille de projets de chaque utilisateur.

## Démarrage

Depuis `scriptsRappro/app-suivi-reconciliation` :

```powershell
uv sync
uv run python manage.py prepare_sqlite_imports --migrate
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

## Campagnes et réimports

Le moteur produit désormais un **unique JSONL v2**, contenant l’inventaire Atlas complet
et les propositions. Le menu **Campagnes** donne accès aux photographies précédentes,
aux changements de montants/statuts et aux absences. Les validations inchangées sont
reprises avec leur date, auteur et campagne d’origine. Les modifications du groupe ou
des preuves imposent une nouvelle revue. Les anciennes campagnes restent en lecture seule.

Au premier import v2, les données déjà présentes sont photographiées dans une archive
signalée sans inventaire complet. Aucun historique absent ne peut être reconstitué.
Après ce passage, les fichiers v1 sans inventaire sont refusés.

Voir le [guide technique et métier des campagnes](../docs/campagnes_rapprochement.md).

## Exercice et portefeuilles

Le moteur accepte `--year 2026` pour limiter Atlas et SAGE au même exercice.
Les campagnes sont comparées à la précédente du même exercice ; la dernière importée
reste la campagne courante de travail.

Le menu administrateur **Importer des portefeuilles** accepte un Excel avec les colonnes
`username` et `code projet`. Un modèle est téléchargeable. Les utilisateurs doivent
exister ; les projets sont contrôlés dans les inventaires Atlas, également lors des
ajouts administratifs depuis **Mon portefeuille**. Un compte classique ne peut
pas s’attribuer lui-même un projet. L'import ajoute des accès sans en supprimer.

Le statut BAP de correction propose exclusivement **Envoyé SAGE** et **Comptabilisé**.
Voir le [guide complet](../docs/filtre_annuel_et_portefeuilles.md).

Voir le [guide de validation](docs/validation-metier.md).

La [note de refonte UI/UX](docs/refonte-ui-ux.md) décrit les écrans, les filtres,
les décisions et les vérifications de non-régression.

## Vérification

```powershell
uv run python manage.py test
uv run ruff check .
```

## Contrôles des multiples et affectations SAGE

La migration `0010_multiple_controls_assignments` ajoute les contrôles de campagne, les affectations de vraies écritures candidates et leurs contributions projetées. Elle doit être appliquée avant le redémarrage. Le package `../reconciliation_contract/` doit être déployé avec l’application. Le [guide français](../docs/multiples_atlas_affectations_export.md) décrit le contrat v3, les confirmations requises, le nouvel export d’audit et les limites métier encore à confirmer.

## Imports SQLite volumineux

Pour PostgreSQL et le déploiement des imports volumineux, voir le
[guide PostgreSQL](../docs/import_postgres.md).

La préparation des campagnes est isolée, les instantanés sont chargés par lots
invisibles et la publication est atomique. Progression et durées sont visibles
dans le suivi de l'import. Voir [la documentation](../docs/import_sqlite_par_lots.md).

Pour mettre à niveau une installation existante, après la fin de tout ancien
import : `uv run python manage.py prepare_sqlite_imports --migrate`, puis redémarrer
le serveur. Cette commande sauvegarde la base, applique les migrations et active
WAL ; elle refuse de s'exécuter si un worker détient encore le verrou.
