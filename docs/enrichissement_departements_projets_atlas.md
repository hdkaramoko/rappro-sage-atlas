# Départements organisationnels des projets Atlas

## Usage

Depuis la racine du dépôt, après mise à jour du moteur :

```powershell
.venv/Scripts/python.exe -m reconciliation.main --atlas "data/inputs/JDD.xlsx" --sage "data/inputs/ZLISTPJT.csv" --year 2026 --atlas-projects "data/inputs/ProjetAtlas.xlsx" --department-mapping "data/inputs/transcodification.xlsx" --review-output "data/outputs/campagne_13112026.jsonl"
```

Les deux nouveaux arguments sont facultatifs ensemble, obligatoires pour une
campagne enrichie. Ils exigent `--review-output` en v3 avec inventaire Sage
complet ; `--legacy-review-output` n'est pas compatible avec ce lot. Les anciennes
commandes sans ces arguments continuent de fonctionner, sans départements.
`--output` peut toujours ajouter le classeur de rapprochement habituel.

Trois sorties sont publiées à côté du JSONL :

- `campagne_13112026.jsonl` : campagne enrichie ;
- `projets_jdd_atlas_campagne_13112026.xlsx` : un code par projet réellement
  présent dans le JDD, département source/consolidé, présence dans le référentiel,
  nombre de lignes et diagnostic d'absence ;
- `projets_sage_absents_jdd_campagne_13112026.xlsx` : différence exacte
  **projets de l'extraction Sage chargée − projets du JDD chargé**, avec nombre
  d'écritures. Tous les types sont inclus, même exclus du cadrage. Aucun total
  financier n'est ajouté. Un projet commun aux sources n'apparaît pas ici même
  s'il comporte des écritures non rapprochées.

Ces inventaires ne sont pas des fichiers d'attribution : l'import des
portefeuilles attend exactement `username` et `code projet`. Pour préparer une
attribution, créer ce gabarit à deux colonnes, copier les codes pertinents et
renseigner les comptes existants manuellement. Aucun droit n'est attribué ici.

## Contrôle des entrées

`ProjetAtlas.xlsx`, feuille `Sheet1`, exige `Code projet` et `Département leader`.
La transcodification, feuille `Feuil1`, exige `Département leader` et
`Département consolidé`. Accents/casse/espaces des en-têtes sont normalisés ;
`Département associé` ne remplace jamais `Département leader`. Les colonnes
supplémentaires sont ignorées sauf pour reconnaître les synthèses. Les formules
dans les colonnes requises sont refusées.

Les codes suivent la fonction de normalisation des codes JDD/Sage (espaces
insécables et périphériques, majuscules). Le référentiel exige des identifiants
Excel textuels, de 1 à 100 caractères alphanumériques, tiret, point ou soulignement.
Une cellule numérique est refusée pour ne pas perdre les zéros initiaux.

Les lignes entièrement vides sont ignorées. Les synthèses sont reconnues par :

1. code absent ou marqueur explicite (`Total`, `Totaux`, `Total général`,
   `Nombre de projets`), département absent et marqueur de total dans la ligne ;
2. code et département absents, avec cellules non vides exclusivement numériques
   dans les colonnes financières connues : `Montant total (€)`, `Part EF (€)`,
   `CA (€)`, `Dépense budgétée (€)`, `Dépenses réalisées (€)`,
   `Prix total dépenses budgétées`.

Aucune suppression positionnelle des deux dernières lignes. Tout autre vrai
enregistrement incomplet/invalide provoque une erreur explicite. Même projet et
même département : dédoublonnage compté ; départements contradictoires : arrêt.
La table de transcodification est intégralement lue, jamais codée en dur.
Les clés de libellés normalisent Unicode NFKC, casse et espaces sans fuzzy.
Un mapping répété identique est dédupliqué ; des cibles différentes sont refusées.
Département source absent, cible vide ou département inconnu : génération arrêtée
avant matching/publication, avec libellés à corriger. Aucun repli vers `AUTRES`.

Un projet JDD absent du référentiel reste dans l'inventaire Atlas, sans département
inventé. Son code figure dans le diagnostic et le bilan JSONL/journal. Le bilan
contient codes uniques Atlas/Sage, intersection, différence, projets sans
département, doublons et synthèses du référentiel.

Le référentiel réel fourni a été validé en lecture seule : sa transcodification
contient 15 associations ; un doublon identique et une ligne de total numérique
ont été détectés dans le référentiel projets. Aucune donnée source n'est modifiée.

## Contrat et persistance

Le schéma reste v3 avec deux champs optionnels indissociables :

```json
{
  "department_policy": "project-departments-v1",
  "project_departments": {
    "PROJET": {"source": "Santé", "consolidated": "SANTE", "in_reference": true},
    "ABSENT": {"source": "", "consolidated": "", "in_reference": false}
  }
}
```

La table apparaît une seule fois dans l'en-tête, accompagné de
`department_summary`. Sa signature est incluse dans l'empreinte du flux existante.
Codes normalisés, libellés de 255 caractères maximum, booléen strict et cohérence
source/cible sont validés côté moteur et import. Le périmètre doit correspondre
exactement aux codes de l'inventaire Atlas présent. Un contrat contradictoire ou
une politique inconnue annule l'import transactionnel. Les flux historiques sans
ces champs restent importables ; aucune valeur par défaut n'est affectée.

La migration `0025_campaign_departments` crée `CampaignDepartment`, avec contrainte
unique `(campaign, project_code)`, département source et consolidé. Elle ne modifie
pas `Project.geography` et ne stocke pas de département courant sur `Project`.
N+1 peut changer le rattachement sans réécrire N. Insertion par lots de 500,
transaction PostgreSQL existante et nouvelle table ajoutée au transfert des lots
SQLite cachés avant publication atomique. Idempotence de l'import conservée.

Les fichiers de la CLI sont préparés dans un répertoire temporaire sur le volume
du JSONL. Chaque sortie est remplacée atomiquement après validation, JSONL en
dernier. Il n'existe pas de transaction multifiche du système de fichiers : une
interruption entre remplacements peut laisser des inventaires plus récents que
le JSONL précédent ; relancer la commande avant de distribuer les sorties.
Aucun fichier partiellement écrit n'est publié.

## Interface et recette

Le filtre s'appelle **Département** et affiche exclusivement les valeurs
**transcodifiées** dans Envoyé SAGE, Contrôle des montants et Cadrage comptable.
Multisélection existante, Toutes en premier et par défaut, Non renseigné si utile.
Les options proviennent du périmètre visible ; les droits restent exclusivement
ceux des portefeuilles. SQL avant pagination, compteurs et tableaux cohérents,
compatibilité avec les autres filtres. Les liens de pagination et de retour
préservent la sélection. Une ancienne campagne reste entièrement non renseignée,
sans requêtes supplémentaires pour charger un référentiel inexistant.

Déployer le moteur et Django puis, depuis `app-suivi-reconciliation` :

```powershell
../.venv/Scripts/python.exe manage.py migrate
```

En SQLite, la procédure habituelle de préparation avant import reste disponible :
`../.venv/Scripts/python.exe manage.py prepare_sqlite_imports --migrate`.
Ne pas appliquer cette commande SQLite à PostgreSQL.

Générer le JSONL avec la commande ci-dessus puis importer via **Importer un
rapprochement**, ou depuis le dossier Django :

```powershell
../.venv/Scripts/python.exe manage.py import_review_bundle ../data/outputs/campagne_13112026.jsonl
```

Vérifier les trois filtres (Toutes, SANTE/P2S selon les données, Non renseigné,
combinaisons, page suivante et retour), puis tester un lecteur au portefeuille
restreint. Aucun recalcul rétroactif des départements des campagnes existantes.

## Tests et coûts mesurés

`tests/test_departments.py` couvre les référentiels, Unicode, les vrais derniers
projets, les totaux numériques, erreurs, absence de mapping, exports ensemblistes,
CLI enrichie, préservation d'une sortie en cas d'échec et corps JSONL identiques.
`reconciliation.test_departments` couvre import, historique, rollback, idempotence,
trois filtres, droits et pagination. Le scénario SQLite sur disque vérifie le
transfert réel du rattachement et son import répété. Les suites métier existantes
vérifient montants, validations et actions persistantes.

Benchmark reproductible, sans base utilisateur :
`.venv/Scripts/python.exe -m examples.benchmark_departments`.
Échantillon : 200 projets, 400 Atlas et 2 000 Sage ; matching exécuté une fois.
Corps JSONL et volumes de contrôle/validation identiques avant/après.

| Mesure SQLite locale | Sans enrichissement | Avec enrichissement et filtre SANTE |
|---|---:|---:|
| Export JSONL | 1,256 s | 1,188 s |
| Taille JSONL | 5 184 270 octets | 5 202 568 octets |
| Import complet | 8,213 s | 9,270 s |
| Envoyé SAGE | 64 ms / 13 requêtes | 59 ms / 15 requêtes |
| Contrôle des montants | 34 ms / 12 requêtes | 45 ms / 14 requêtes |
| Cadrage | 28 ms / 15 requêtes | 32 ms / 17 requêtes |

Mesures ponctuelles, non garanties sur campagne complète : la variation de
durée ne démontre pas de gain à l'export. Le coût d'import observé inclut aussi
les contrôles/comparaisons complets ; deux requêtes supplémentaires par vue,
aucun N+1. Test supplémentaire : filtre/pagination sur 1 000 projets matérialisés.
PostgreSQL réel n'a pas été mesuré dans cet environnement SQLite.

Commandes de validation : `.venv/Scripts/python.exe -m pytest -q` à la racine ;
`../.venv/Scripts/python.exe manage.py test --noinput` dans le dossier Django.

Résultats : **323 tests moteur réussis, un test réel optionnel ignoré** ;
**430 tests Django sans échec, dont trois tests PostgreSQL ignorés sous SQLite**.
Les 17 tests départementaux du moteur ont aussi été rejoués après finalisation
des sorties. Migration cohérente (`makemigrations --check --dry-run`), syntaxe
et documentation des nouvelles fonctions vérifiées, contrôle Ruff des imports
avec conservation des réexports de modèles Django existants, `git diff --check`
sans erreur. Aucune migration appliquée à la base utilisateur pendant ce lot.

Fichiers principaux : `reconciliation/departments.py` (référentiels/exports),
`reconciliation/main.py` (CLI et publication), `reconciliation/exporters/review.py`
(en-tête), `reconciliation_contract/departments.py` (validation partagée).
Côté Django : modèle/migration `CampaignDepartment`, `campaigns.py`, transfert
`imports_app/sqlite_staging.py`, helper `reconciliation/departments.py` et les
trois vues `review_views.py`, `global_views.py`, `accounting_views.py`.
Le composant multisélection et les liens de navigation existants sont réutilisés.
