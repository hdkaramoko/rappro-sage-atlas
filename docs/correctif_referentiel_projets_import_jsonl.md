# Référentiel des projets à l'import JSONL

Les nouveaux imports v2/v3 créent désormais les projets de tout l'inventaire
Atlas, même sans proposition de rapprochement. Le tableau de bord conserve sa
définition : projets actifs accessibles à l'utilisateur.

## Implémentation

Dans `reconciliation/campaigns.py`, `synchronize_inventory_projects()` lit les
codes normalisés distincts de l'inventaire courant par lots de 500. Elle compare
ces codes au référentiel, crée uniquement les absents avec `bulk_create()` et
le libellé de repli « Projet importé », puis retourne le cache utilisé par les
propositions. Aucun détail financier de l'inventaire n'est chargé pour cette
synchronisation. Les lectures du référentiel dépendent des lots de codes,
pas du nombre de lignes Atlas ni du nombre de propositions.

L'appel intervient au premier enregistrement qui suit les lignes `inventory`,
après insertion du dernier lot Atlas. Il fonctionne également sans proposition,
avant l'inventaire Sage, les contrôles ou le marqueur final selon le format.
Les validations restantes du flux sont inchangées et restent obligatoires.

La transaction parente de `import_bundle()` annule aussi les créations de
projets si le flux échoue. Le circuit SQLite prépare ces créations sur sa copie
privée ; `projects_project` appartient déjà aux tables transférées dans la
transaction atomique de publication. Aucun changement du staging n'est requis.

Les projets existants ne sont pas mis à jour : libellés, géographie, dates,
statut inactif et autres métadonnées sont conservés. Aucun portefeuille n'est
créé ou modifié. Le chemin historique v1 garde son comportement. Le moteur,
le JSONL, les validations et les calculs comptables ne sont pas modifiés.

Les opérations ORM utilisées sont communes à SQLite/PostgreSQL. La relecture
groupée des projets créés évite de dépendre de la restitution des identifiants
par `bulk_create()`. Les contraintes d'unicité restent actives ; aucune erreur
de contrainte n'est silencieusement ignorée. Aucun test sur un serveur
PostgreSQL réel n'a été exécuté pour ce correctif.

## Vérifications

- `reconciliation/test_inventory_projects.py` : base vierge, projets sans
  proposition, v2/v3, codes normalisés et lots, imports successifs, préservation
  des données et portefeuilles, rollback, budget SQL et accès serveur.
- `reconciliation/test_campaigns.py` : réutilisation du cache par les propositions.
- `imports_app/sqlite_scenarios.py` : transfert réel des projets sans proposition,
  conservation après un second import, et rollback des projets lors d'une panne
  en pleine publication. La fixture département/pôle utilise l'environnement
  Python du moteur, comme les autres tests qui génèrent un JSONL.

Commandes depuis `app-suivi-reconciliation` :

```powershell
.venv/Scripts/python.exe manage.py test reconciliation.test_inventory_projects reconciliation.test_campaigns --noinput
.venv/Scripts/python.exe manage.py test --noinput
```

Résultats exécutés : suite complète de 440 tests, `OK (skipped=3)`, en
205,7 secondes ; les trois tests ignorés exigent un serveur PostgreSQL.
Les huit tests ciblés du nouveau module passent également.
Les tests sur disque incluent le nouveau scénario et le rollback des projets.
Le contrôle Ruff du nouveau module, les règles Ruff `F` des modules existants
modifiés, ainsi que `git diff --check`, passent.

Une recette complète du JSONL réel du 13 novembre a été lancée sur une base
SQLite neuve isolée dans `.work_app/recette-referentiel-nde82ku1/`. Elle a été
arrêtée à la demande de l'utilisateur pendant la préparation des contrôles
globaux, après chargement des inventaires, propositions et contrôles, puis les
validations automatiques. La publication et les compteurs finaux de cette
recette réelle ne sont donc pas validés. L'utilisateur effectuera cet essai.
La base SQLite de l'application existante n'a pas été modifiée par cette recette.

## Recette sur base vierge

Utiliser une installation de recette séparée avec une nouvelle base SQLite,
puis exécuter `prepare_sqlite_imports --migrate`, créer un administrateur et
importer le JSONL existant via l'interface ou `import_review_bundle`. Ne pas
régénérer le JSONL. Aucun rattrapage des bases existantes n'est fourni.
Un fichier déjà importé reste traité comme un doublon : son réimport sur la même
base ne déclenche pas de synchronisation rétroactive.

Sur le JSONL `campagne_13112026.jsonl`, une base vierge doit contenir 1 568
projets Atlas et autant de `Project`. Pour un administrateur global, le tableau
de bord doit afficher 1 568 projets et le cadrage 1 018 projets cadrés.

Le calcul comptable inclut aussi les 56 projets Sage seuls : les 1 624 synthèses
ne doivent pas être confondues avec les 1 568 projets Atlas du référentiel. Les
projets inactifs, les portefeuilles restreints et l'indisponibilité d'un cadrage
peuvent légitimement faire varier les chiffres affichés sur d'autres bases.
