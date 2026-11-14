# Cadrage : totaux alignés sur le périmètre filtré

## Affichage

Le bandeau permanent nom/exercice/date de campagne est retiré de la liste.
La sélection implicite de campagne, ses métadonnées et les messages
d'indisponibilité ou de paramètre historique sont conservés.

Une ligne « Total du périmètre filtré » précède les projets dans le même tableau,
avec le nombre de projets. Ses quatre montants suivent les colonnes Atlas
initial, Atlas retenu, Sage retenu et Écart. Les cellules État et Action restent
vides. La ligne est placée en première ligne du `tbody`, avec un en-tête de
ligne `scope="row"` : cela préserve la sémantique et l'alignement sans superposer
deux lignes d'en-tête sticky. Le fond contrasté distingue la synthèse.

Atlas initial reste visible sur mobile ; le tableau défile horizontalement dans
une région nommée, accessible au clavier et dotée d'un contour de focus. Les
formats existants `euros` et `signed_euros` sont réutilisés.

## Calcul et précision

`accounting_list()` transmet à `filtered_totals()` le queryset après tous les
filtres de visibilité, département, pôle, projet, état et recherche, avant
pagination. Les montants retenus et l'écart sont totalisés depuis les colonnes
`AccountingProject.atlas`, `sage`, `gap`, sans recalculer les montants par projet.

Atlas initial est extrait par SQL depuis `data.totals.initial`. Aucun document
JSON complet de l'ensemble du périmètre n'est décodé côté application.

- PostgreSQL : extraction texte JSON, conversion `NUMERIC` sans échelle imposée,
  puis `SUM`, avec retour texte converti en `Decimal`.
- SQLite : agrégat temporaire enregistré sur la connexion par la vue. Il reçoit
  seulement les scalaires SQL textuels et les additionne en `Decimal` avec une
  précision de 60 chiffres. Les résultats reviennent comme texte pour éviter
  le convertisseur flottant des sommes numériques SQLite. Les valeurs initiales
  préparées sont des chaînes décimales ; aucune nouvelle conversion en `float`
  n'est introduite. Les limites préexistantes du stockage numérique SQLite des
  colonnes retenues restent celles des montants par projet ; ce correctif ne
  change pas leur stockage.

Cette stratégie n'exige ni migration, ni matérialisation, ni reconstruction des
synthèses existantes. L'agrégat SQLite est local à la connexion et ne modifie pas
la base. Les formules, statuts comptables et décisions restent inchangés.

Pour chaque colonne, un décompte des valeurs connues accompagne la somme. Si une
valeur manque, la cellule affiche « — » et « Incomplet : N montants absents » ;
elle ne présente pas la somme partielle comme un total complet. Les autres
colonnes restent affichables indépendamment. Le zéro réel reste « 0,00 € ».
Sans résultat, aucune ligne de totaux n'est affichée et le message vide habituel
reste visible. Le total Écart est la somme des écarts stockés, sans substitution
par une différence susceptible de masquer des valeurs absentes.

## Coût et limites

Une seule requête agrégée produit les quatre sommes, leurs nombres d'absences
et l'effectif total. Cet effectif alimente aussi le cache du paginateur pour
éviter une seconde requête `COUNT`. Le nombre total de requêtes de la liste
n'augmente donc pas. Le coût CPU reste proportionnel au nombre de projets
filtrés ; SQLite appelle l'agrégat Decimal pour chaque scalaire non nul.
Les options des filtres et les 40 synthèses de la page sont lues comme avant.

La compatibilité PostgreSQL est revue et sa compilation SQL est testée sans
connexion serveur. Les tests d'intégration PostgreSQL réels ne sont pas exécutés
dans cet environnement.

## Vérifications et fichiers

- `reconciliation/accounting_totals.py` : agrégations et traitement des absences.
- `reconciliation/accounting_views.py` : appel après filtres et réutilisation de
  l'effectif pour la pagination.
- `templates/reconciliation/accounting_list.html` et `static/css/workspace.css` :
  retrait du bandeau, ligne de totaux, styles et accessibilité.
- `reconciliation/test_accounting_totals.py` : filtres seuls/combinés, droits,
  pagination au-delà de 40 projets, valeurs négatives/nulles, grands décimaux,
  cohérence de l'écart, requêtes et compilation PostgreSQL.
- `reconciliation/test_accounting_ux.py` : attente du bandeau retirée ; le contrôle
  de la campagne implicite et de sa date côté backend est conservé.

La recette navigateur est réalisée sur la vraie vue rendue avec données fictives
et CSS locales, à 390 px et 1440 px. Les mesures DOM vérifient les mêmes positions
et largeurs pour chaque colonne de l'en-tête, des totaux et des projets, avant et
après défilement horizontal. Aucun débordement de page n'est constaté. Les
captures de recette sont conservées dans `.work_app/accounting-totals-mobile.png`
et `.work_app/accounting-totals-desktop.png`.

Commande de tests depuis `app-suivi-reconciliation` :

```powershell
.venv/Scripts/python.exe manage.py test --noinput
```

Résultat exécuté : **449 tests, OK (3 ignorés car PostgreSQL requis)** en
194,8 secondes. Les 33 tests ciblés liste/détail/départements passent également.
Ruff sur les deux nouveaux modules, les règles `F` sur les modules Python
existants modifiés et `git diff --check` passent.

Mesures locales de la dernière exécution (indicatives, sans garantie de délai) :

| Recette | Temps | Requêtes |
| --- | ---: | ---: |
| Sommes seules, 1 000 projets avec JSON de 4 Ko | 0,012 s | 1 |
| Liste filtrée/paginée, 120 projets et 12 000 groupes | 0,033 s | 15 |
| Liste avec département, 1 000 projets | 0,056 s | 17 |
| Liste avec département et pôle, 1 000 projets | 0,054 s | 19 |

Aucun import du JSONL réel n'est lancé pour ce correctif UX.
