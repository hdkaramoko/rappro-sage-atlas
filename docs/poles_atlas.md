# Pôle Atlas : configuration, campagne et filtres

## Configuration nécessaire

Le circuit existant Département lit désormais également la colonne **Pôle** de
`data/inputs/ProjetAtlas.xlsx`, feuille `Sheet1`. `Pôle associé` ne la remplace pas.
Les totaux, codes projets et contradictions sont contrôlés comme auparavant.
Deux lignes d'un même projet portant des pôles différents sont refusées, même
si les deux pôles seraient classés Hors DP. Les espaces, la casse et Unicode
sont normalisés pour comparer ; la valeur source brute reste conservée.

Renseigner dans **`reconciliation/config.py`** :

- `POLES_SUIVIS` : liste des libellés métier réellement suivis, avec leur graphie
  exacte à afficher ;
- `POLE_PAR_DEFAUT = "Hors DP"` : repli contractuel obligatoire.

La configuration contient les **12 pôles validés par l'utilisateur** :
DP Angola, DP Comores, DP Côte d'Ivoire, DP Ethiopie, DP Guinée, DP Haïti,
DP Jordanie/Liban, DP Madagascar, DP République Démocratique du Congo,
DP Rwanda, DP Tunisie/Lybie et DP Ukraine. Ils ont tous une correspondance exacte
dans le référentiel réel fourni. Sur son périmètre propre (pas une campagne),
245 projets uniques appartiennent à ces pôles, 4 186 sont Hors DP.

Si une configuration ultérieure est remise à `POLES_SUIVIS = None`, une nouvelle
génération enrichie échoue explicitement au lieu de publier des classifications trompeuses.
Une liste vide `[]` est acceptée seulement comme choix explicite de ne suivre
aucun pôle ; tous les projets deviennent alors Hors DP. Ne pas copier les noms
des tests comme configuration métier. L'extraction n'est jamais utilisée pour
déduire arbitrairement la liste des pôles à suivre.

Une valeur suivie conserve exactement le nom configuré, sans transcodification.
Valeur non suivie, nulle ou vide : Hors DP. Projet absent du référentiel : Hors DP
et source vide, avec `in_reference=false` et diagnostic d'absence. Le bilan
compte les projets par pôle, y compris Hors DP, les pôles source vides dans le
référentiel et les projets manquants. Changer la configuration ne s'applique
qu'aux prochaines campagnes générées.

## Contrat JSONL v3

Le champ `project_departments` existant reste une table par projet ; aucun champ
organisationnel n'est répété dans les écritures ou propositions. Les nouveaux
en-têtes ajoutent `pole_policy: project-poles-v1` et `pole_configuration`, avec
`followed` (liste explicite des noms suivis) et `fallback: Hors DP`.

Chaque rattachement conserve `source`, `consolidated`, `in_reference`, et ajoute :

- `pole` : nom suivi exact ou Hors DP ;
- `pole_source` : chaîne brute Excel, vide si absente, espaces inclus pour l'audit.

L'import valide le couple source/classification contre la configuration **du
JSONL**, jamais contre la configuration actuelle du moteur. Politique inconnue,
champ manquant, nom ambigu, repli différent ou classification contradictoire :
import annulé. L'empreinte de flux existante couvre ces métadonnées.
Les anciens JSONL sans pôle restent valides, qu'ils contiennent ou non Département.

L'export `projets_jdd_atlas_*.xlsx` ajoute Pôle et Pôle source après les six colonnes
existantes. L'export Sage absent du JDD reste inchangé : il ne portait pas de
métadonnées départementales. Ces inventaires restent des supports préparatoires,
pas des fichiers directement importables en portefeuille : ce dernier attend
exactement `username` et `code projet`, toujours sans changement.

## Django et interface

La migration **0026_campaign_poles** étend `CampaignDepartment` avec `pole` et
`pole_source`. Valeurs anciennes : Hors DP et chaîne vide. La photographie reste
unique par campagne et projet ; aucune valeur courante sur `Project`, aucune
modification de `geography` ni des portefeuilles. Le transfert SQLite par lots
réutilise la même table et copie les nouvelles colonnes ; le circuit PostgreSQL
reste transactionnel. Aucun recalcul rétroactif.

Le filtre **Pôle** apparaît dans Envoyé SAGE, Contrôle des montants et Cadrage
comptable. Multisélection, Toutes par défaut et en premier, pôles réellement
visibles et Hors DP si présent. Les options viennent du portefeuille autorisé
avant combinaison avec les autres filtres. SQL avant pagination et compteurs ;
URL, pagination et liens de retour conservent les choix. Département et Pôle
partagent le même helper organisationnel ; les anciennes campagnes ne déclenchent
pas de recherches supplémentaires pour reconstituer des pôles inexistants.

La grille desktop passe à six menus et une recherche de trois parts ; les
comportements tablette/mobile précédents sont conservés. Recette Chrome sur les
deux vues à 320, 375, 390, 430, 768, 1024, 1440 et 1920 px : 16 cas sans
débordement, menus ouverts inclus et multisélections fonctionnelles. À 1440 px,
les sept champs tiennent sur une rangée, recherche d'environ 345 px. Captures
et rapports locaux : `benchmarks/review_filters/` (ignoré par Git).

## Mise en service

Après déploiement du moteur/Django (les 12 pôles sont déjà configurés), depuis le
dossier `app-suivi-reconciliation` :

```powershell
../.venv/Scripts/python.exe manage.py migrate
```

Depuis la racine, générer un **nouveau** JSONL :

```powershell
.venv/Scripts/python.exe -m reconciliation.main --atlas "data/inputs/JDD.xlsx" --sage "data/inputs/ZLISTPJT.csv" --year 2026 --atlas-projects "data/inputs/ProjetAtlas.xlsx" --department-mapping "data/inputs/transcodification.xlsx" --review-output "data/outputs/campagne_poles_13112026.jsonl"
```

Importer via le menu habituel ou, depuis le dossier Django :

```powershell
../.venv/Scripts/python.exe manage.py import_review_bundle ../data/outputs/campagne_poles_13112026.jsonl
```

Vérifier un pôle suivi, Hors DP, Toutes et les combinaisons Département/Pôle dans
les trois vues, puis pagination et droits d'un lecteur restreint.
Pour ajouter ultérieurement un pôle suivi : modifier la liste de configuration,
générer/importer une nouvelle campagne. Les anciennes gardent leur classification.

## Validation et performances

Suites exécutées : **331 tests moteur réussis, un test réel optionnel ignoré** ;
**432 tests Django sans échec, trois tests PostgreSQL ignorés sous SQLite**.
Le scénario sur disque exerce réellement la copie privée, les nouvelles colonnes,
la publication et l'idempotence. Les tests ciblés couvrent lecture, espaces,
absence de configuration, erreurs, contradictions, anciennes campagnes, nouvelles
classifications, permissions, pagination et sources métier inchangées.

Commandes : `.venv/Scripts/python.exe -m pytest -q` à la racine ;
`../.venv/Scripts/python.exe manage.py test --noinput` dans Django.
Le contrôle de migration ne détecte aucun changement non migré.

Benchmark reproductible et isolé :
`.venv/Scripts/python.exe -m examples.benchmark_departments --poles`.
Comparaison Département seul / Département + Pôle, 200 projets, 400 Atlas,
2 000 Sage. Même matching, corps JSONL identiques, mêmes quantités et cadrages
financiers par projet ; les requêtes portent sur le même périmètre.

| Mesure locale SQLite | Département seul | Avec Pôle |
|---|---:|---:|
| Export JSONL | 1,438 s | 1,657 s |
| Taille JSONL | 5 202 568 octets | 5 212 279 octets |
| Import complet | 10,259 s | 10,454 s |
| Envoyé SAGE | 62 ms / 15 requêtes | 62 ms / 17 requêtes |
| Contrôle des montants | 53 ms / 14 requêtes | 52 ms / 16 requêtes |
| Cadrage | 43 ms / 17 requêtes | 37 ms / 19 requêtes |

Deux requêtes supplémentaires par vue enrichie, aucune requête par écriture.
Test de combinaison Département/Pôle sur 1 000 projets : 48 ms, 19 requêtes.
Ces mesures ponctuelles ne démontrent pas de gain de vitesse ; elles ne préjugent
pas d'une campagne complète ni de PostgreSQL. Aucun nouvel index n'est ajouté :
la contrainte existante campagne/projet est réutilisée et ces mesures ne justifient
pas d'index supplémentaire.

Fichiers principaux : configuration et lecteur/export projets
`reconciliation/config.py`, `departments.py`, export JSONL `exporters/review.py`,
contrat partagé `reconciliation_contract/departments.py`. Django : modèle,
migration 0026, `campaigns.py`, helper `departments.py`, trois vues et
`static/css/workspace.css`. Tests/fixtures/benchmark et scénario SQLite adaptés.
Aucune règle de matching, tolérance, validation, persistance des décisions ou
formule de cadrage n'est modifiée.
