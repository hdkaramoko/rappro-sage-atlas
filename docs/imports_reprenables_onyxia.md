# Imports JSONL reprenables sur Onyxia

## Périmètre et limites livrées

Le chemin PostgreSQL des campagnes v2/v3 charge durablement les inventaires
Atlas, Sage et l'historique BAP, dans une campagne privée réutilisée à chaque
tentative. Les identités des propositions/contrôles et les couples projet/BAP
sont indexés en base. Chaque lot et son checkpoint partagent la même transaction.
Le fichier source doit rester sur le PVC ; PostgreSQL conserve l'état du job.

**La finalisation métier reste monolithique et potentiellement longue.** Elle
relit les propositions et contrôles, applique les projections, reports,
auto-validations, cadrage et préparation comptable, puis publie dans une seule
transaction. Une interruption à ce stade rejoue toute cette phase, mais ne
réinsère pas les inventaires déjà validés. Ce lot ne garantit donc pas une reprise
fine de la préparation comptable ni une RAM bornée dans tous les services métier
existants. Mesurer cette limite sur 1,6 Go avant toute promotion en production.

Ce choix évite de commiter des projections visibles partielles. Rendre cette
dernière phase reprenable par projet nécessiterait de versionner les projections
globales et leurs allocations, puis d'adapter toutes leurs lectures et écritures.
Ce changement structurel n'est pas dissimulé derrière `published=False`.

SQLite conserve sa copie privée et sa publication atomique existantes ; il ne
bénéficie pas des checkpoints PostgreSQL. Le format v1 et l'import direct
`import_review_bundle` conservent leur ancien chemin atomique. Aucun changement
du moteur, des fichiers v1/v2/v3 ou des règles métier.

## Audit et répartition des écritures

L'audit de la branche a confirmé les deux transactions englobantes
(`run_job`, `import_bundle`), le `subprocess.Popen` local, les heartbeats sur
disque et les ensembles en RAM dans `import_campaign`. Les campagnes possédaient
déjà un manager `objects` filtrant `published=True` et un manager `all_objects`.

| Étape | Écritures | Visibilité / transaction |
| --- | --- | --- |
| Upload | Fichier temporaire, identité brute, `MatchingJob` | Fichier complet et synchronisé avant `QUEUED` |
| En-tête | Une `Campaign` privée, `CampaignDepartment` | Transaction courte ; aucun `Project` créé |
| Atlas | `CampaignInventory`, index des couples BAP | Lots courts et checkpoint commun |
| BAP | `CampaignBapHistory` | Lots courts ; couples Atlas validés par index persistant |
| Sage | `CampaignSageEntry` | Lots courts ; contraintes uniques existantes conservées |
| Propositions / contrôles | `ImportIdentity` | Identités uniques inter-lots ; validations détaillées à la finalisation |
| Finalisation | `Project`, `ReviewGroup`, `ReconciliationTransaction`, `LineReview`, snapshots, décisions, allocations, contrôles, index, agrégats comptables | Une transaction avec gel des écritures métier |
| Publication | Bascule courante, `published`, `SUCCESS`, révisions et maintenance après commit existantes | Même transaction que les projections finales |

Les vues de campagne/inventaire filtrent la publication ; les vues de cadrage,
contrôles, tableaux de bord et portefeuilles partent des campagnes publiées ou
courantes. Les accès métier directs à un inventaire verrouillent sa campagne et
refusent une campagne non publiée. Aucune projection globale n'est modifiée
pendant le staging. Le hash d'une campagne privée ne constitue pas un doublon.

Les décisions ordinaires verrouillent la campagne, le groupe et la ligne ; les
actions comptables verrouillent aussi la campagne. Les anciennes corrections
de transactions ont leur propre verrou et leur version. Pour couvrir également
ces dernières, la publication acquiert des verrous PostgreSQL
`SHARE ROW EXCLUSIVE` sur les tables des applications `reconciliation` et
`projects`, **avant** de relire les décisions. Les SELECT ordinaires continuent
de voir la campagne précédente ; les écritures attendent. Un délai d'acquisition
de 10 secondes permet d'échouer proprement sur un conflit. Le suivi annonce
explicitement ce gel, dont la durée reste à mesurer.

## État durable et protocole

`MatchingJob` porte `protocol_version`, `phase`, `next_offset` (octets),
`line_number`, `committed_batches`, `checkpoint` (section, compteurs et temps),
`source_size`, SHA-256 brut, `heartbeat_at`, `attempts`, `resumed_at`,
`next_attempt_at` et `generation`. Le lien unique `Campaign.job` garantit une
seule campagne de staging. Migration additive : `imports_app.0004`.

| État | Transition / réservation |
| --- | --- |
| `UPLOADING` | Upload en cours ; aucune reprise HTTP partielle. Abandon manuel si le serveur s'arrête. |
| `QUEUED` | Source complète ; réservation unique `active=True`. |
| `IMPORTING` | Worker détenteur du verrou ; récupération possible après arrêt brutal. |
| `INTERRUPTED` | SIGTERM ou arrêt contrôlé ; reprise automatique bornée si éligible. |
| `RETRYABLE` | Erreur technique ; backoff si transitoire, sinon correction et reprise explicites. |
| `FAILED` | Erreur de contrat / intégrité définitive ; abandon ou nouvel import corrigé. |
| `SUCCESS`, `DUPLICATE`, `ABANDONED` | Terminaux, `active=False` ; jamais rejoués. |

Un job reprenable peut avoir `active=False` après épuisement des tentatives ou
source absente/version incompatible. Le bouton Reprendre ou `--resume` réserve
de nouveau la file ; la contrainte `one_active_matching_job` protège les conflits
avec un autre import. `active` désigne donc la réservation de la file, pas la
preuve qu'un processus tourne. Le heartbeat périmé est un diagnostic uniquement.

Les anciens jobs ont un protocole 0. Les succès/échecs historiques restent
consultables ; un job actif sans source JSONL, hors upload, devient `FAILED`
avec diagnostic lors de la migration. Les anciens jobs actifs avec source peuvent
repartir de zéro ; aucun checkpoint historique n'est inventé. Une version de
protocole inconnue exige un binaire compatible, sans retry automatique.

La lecture des lots est binaire, UTF-8 ligne par ligne ; `tell()` n'est enregistré
qu'après un enregistrement entier. Un crash avant commit annule le lot et son
checkpoint ; après commit le lot suivant est lu à l'offset enregistré. Les vrais
doublons sont refusés par les contraintes SQL, sans `ignore_conflicts`. Le seul
`get_or_create` d'identité concerne les couples BAP légitimement partagés.

À chaque tentative, une première relecture streaming vérifie le SHA-256 brut,
la taille, le marqueur de fin, l'absence de données après celui-ci et l'empreinte
normalisée du contrat Sage. Aucun hexdigest n'est utilisé comme état hashlib.
Cette relecture complète n'est pas un rejeu des écritures. Les validations métier
existantes restent appliquées lors de la publication. Les compteurs durables
décrivent les sources préparées ; ils ne promettent pas de pourcentage final.
Le dernier temps de validation et le temps de publication réussie figurent dans
le checkpoint ; les autres mesures par phase sont dans `import.log`.

## Worker, concurrence et arrêt

`MATCHING_JOB_RUNNER=supervised` désactive `Popen` dans le web. Le worker
`matching_worker` consomme les jobs en base et récupère aussi les jobs actifs
interrompus, uniquement après acquisition du verrou PostgreSQL de session
734129826. La session physique et la présence du verrou sont contrôlées avant
les écritures de lot et la publication ; un jeton de génération est aussi
vérifié. La reconnexion silencieuse d'un ancien worker est refusée. Utiliser une
connexion PostgreSQL directe ou du pooling **par session**, jamais par transaction.

Le heartbeat est mis à jour toutes les 10 secondes via une connexion distincte.
Une défaillance de ce suivi demande l'arrêt. Les erreurs techniques ont un
backoff exponentiel plafonné à 300 secondes, avec 3 tentatives par défaut ; une
source absente, une erreur métier ou une version inconnue ne boucle pas.
Les décisions prises pendant le staging sont relues sous les verrous de
publication ; les versions et contrôles métier existants restent appliqués.

SIGTERM demande l'arrêt : le lot non validé est annulé au prochain contrôle.
Une finalisation longue ne peut s'interrompre qu'à sa prochaine frontière de
contrôle ; si Kubernetes tue le processus après le délai de grâce, PostgreSQL
annule la transaction. Le staging est conservé. Aucun worker n'est lancé au
démarrage de chaque processus Gunicorn.

Depuis la racine du dépôt :

```sh
uv run python app-suivi-reconciliation/manage.py matching_worker
uv run python app-suivi-reconciliation/manage.py run_matching_job UUID --resume
# One-shot sans UUID : récupère au plus un job éligible, sans interaction.
uv run python app-suivi-reconciliation/manage.py run_matching_job
```

La commande one-shot renvoie 0 sur succès, doublon ou file vide ; 1 sur échec,
interruption/retry, verrou occupé ou configuration invalide. Un superviseur doit
gérer ce code, sans supposer qu'un retry a publié la campagne. SQLite reste en
runner `local`, avec la commande de secours conservée.

## Stockage et paramètres

| Variable | Défaut |
| --- | --- |
| `MATCHING_JOB_ROOT` | `BASE_DIR/var/matching` en local |
| `MATCHING_JOB_RUNNER` | `local` ; `supervised` sur Onyxia |
| `FILE_UPLOAD_TEMP_DIR` | Répertoire temporaire système ; PVC `/var/lib/rappro/imports/tmp` sur Onyxia |
| `MATCHING_IMPORT_BATCH_SIZE` | 500 ; mesurer avant de passer à 1 000–5 000 |
| `MATCHING_MAX_ATTEMPTS` | 3 |
| `MATCHING_HEARTBEAT_TIMEOUT` | 120 secondes |
| `MATCHING_RETENTION_DAYS` | 30, nettoyage explicite |

Dans Docker, `BASE_DIR=/app/app-suivi-reconciliation`. Le montage est
`/var/lib/rappro/imports` : il ne recouvre jamais le code. Les manifests de chaque
environnement ont un PVC distinct, initialement 20 Gi, sans StorageClass inventée.
Le web et le worker sont deux conteneurs **du même pod**, compatibles avec RWO.
Le Deployment conserve une réplique et utilise `Recreate` pour éviter deux pods
sur des nœuds distincts. Ce choix peut provoquer une indisponibilité web pendant
le redéploiement ; vérifier la contrainte avant d'envisager RWX ou plusieurs pods.
Le worker a ses propres ressources ; budget pod web+worker jusqu'à 8 Gi de RAM.

UID/GID et `fsGroup` : 1000. L'initContainer crée le répertoire temporaire ; le
pilote CSI doit honorer les permissions du volume. Les commandes utilisent
directement `/app/.venv/bin/python` et Gunicorn pour ne pas écrire dans le code
ou le cache uv avec cet UID. Aucun droit Kubernetes n'est donné au web.

L'upload écrit sous `propositions.uploading`, synchronise le fichier puis le
renomme atomiquement en `propositions.jsonl` et synchronise le répertoire Linux.
Un transfert inter-volumes passe par une copie vers le nom temporaire du volume
cible. L'espace libre est contrôlé sur la racine d'import, avec une marge de
1 Gi ; vérifier aussi l'espace du tampon HTTP si celui-ci utilise un autre
volume. Un upload interrompu ne devient pas `QUEUED`. Le PVC n'est jamais
supprimé par un nettoyage applicatif ni par les manifests de Deployment.

## Bootstrap DEV, puis recette PREPROD

Le pipeline existant construit/publie les images ; il ne déployait pas Kubernetes.
Le bootstrap PVC et le déploiement restent donc **manuels**. Le nouveau workflow
`imports-postgresql.yml` fournit une base PostgreSQL éphémère et teste les vraies
transactions, la concurrence et la mort d'un processus. Ne pas promouvoir sans
résultat vert et recette volumétrique. Aucun déploiement n'a été exécuté depuis
le poste de développement : aucun contexte kubectl n'y est configuré.

Commandes Bash d'administration (contexte et namespace à vérifier) :

```sh
kubectl config current-context
kubectl get storageclass
kubectl -n user-hdkaramoko get resourcequota,pvc
# Adapter storage: 20Gi et éventuellement storageClassName dans le manifeste
# selon la classe disponible, le quota, les artefacts conservés et la rétention.
kubectl apply -f k8s/dev/imports-pvc.yaml
kubectl -n user-hdkaramoko get pvc rappro-imports-dev -o wide
kubectl -n user-hdkaramoko describe pvc rappro-imports-dev
```

Une classe `WaitForFirstConsumer` peut laisser le PVC Pending avant création du
pod ; vérifier le mode de binding. Les Jobs `imports-migrate.yaml` permettent
d'exécuter les migrations du **nouveau** binaire avec les secrets du bon environnement,
avant le démarrage du worker. Ils n'ont pas de montage PVC et ne sont pas appliqués
automatiquement par le pipeline.
Ne pas utiliser la base de production du `.env` local. Les secrets existants sont
référencés par `secretKeyRef` ; ne pas les recopier en clair. Pour une installation
existante, sauvegarder PostgreSQL et vérifier `showmigrations` avant migration.

Après migration, remplacer les **trois** occurrences d'image (`web`, worker,
initContainer) par le même tag construit. Exemple depuis la racine :

```sh
IMAGE=ghcr.io/hdkaramoko/rappro-sage-atlas:dev-SHA_VERIFIE
sed "s|ghcr.io/hdkaramoko/rappro-sage-atlas:dev-<sha>|$IMAGE|g" \
  k8s/dev/imports-migrate.yaml | kubectl apply -f -
kubectl -n user-hdkaramoko wait --for=condition=complete job/rappro-imports-migrate-dev --timeout=300s
kubectl -n user-hdkaramoko logs job/rappro-imports-migrate-dev
# Ne continuer que si les migrations sont terminées avec succès.
sed "s|ghcr.io/hdkaramoko/rappro-sage-atlas:dev-<sha>|$IMAGE|g" \
  k8s/dev/deployment.yaml | kubectl apply -f -
kubectl -n user-hdkaramoko rollout status deployment/rappro-sage-atlas-dev
kubectl -n user-hdkaramoko logs deployment/rappro-sage-atlas-dev -c matching-worker --tail=100
kubectl -n user-hdkaramoko exec deployment/rappro-sage-atlas-dev -c matching-worker -- \
  /app/.venv/bin/python /app/app-suivi-reconciliation/manage.py showmigrations imports_app
kubectl -n user-hdkaramoko exec deployment/rappro-sage-atlas-dev -c matching-worker -- \
  sh -c 'id; df -h /var/lib/rappro/imports; test -w /var/lib/rappro/imports/tmp'
```

Préserver les Service/Ingress existants et leurs timeouts. Le worker et le PVC
sont intégrés au Deployment et au manifeste PVC, sans nouveau Service réseau.
Les fichiers PREPROD/PROD sont préparés avec leurs noms, images et secrets
distincts ; **aucune migration ni action destructive PROD sans validation humaine**.
Un Job de migration déjà terminé doit être supprimé explicitement avant une
nouvelle exécution avec le même nom, ou renommé pour la release suivante. Ne
jamais supprimer le PVC. Les Jobs terminés expirent seuls après 24 heures.

Recette à consigner pour DEV, puis PREPROD :

1. Vérifier backend PostgreSQL, montage, permissions, capacité réelle, ressources
   et disponibilité du worker. Importer une petite fixture valide.
2. Attendre plusieurs lots, relever UUID, offset, ligne, compteurs et campagne
   visible. Modifier une décision dans l'ancienne campagne pendant le staging.
3. Supprimer/recréer le pod DEV identifié (web et worker partagent ce pod), puis
   vérifier conservation du fichier, même UUID/campagne privée, reprise au
   checkpoint, décisions conservées et absence de doublons.
4. Provoquer une interruption pendant la finalisation : l'ancienne campagne reste
   intacte ; le redémarrage réutilise les inventaires et rejoue la finalisation.
5. Vérifier publication unique, index/révisions, cadrage, export et contrôles.
   Tester double clic, source absente/modifiée, abandon et nouvel import ensuite.
6. Refaire avec 1,6 Go si disponible. Relever temps de vérification et par phase,
   temps de publication/gel des écritures, RSS max du worker, espace PVC et base,
   WAL produit (`pg_stat_wal.wal_bytes`, à isoler des autres activités) et coût de
   reprise. Le JSONL n'est pas stocké dans un BinaryField.

## Récupération, abandon et rétention

L'administration affiche phase, compteurs durables, checkpoint, heartbeat,
tentatives, erreur et les actions POST protégées CSRF. La reprise garde l'UUID,
le fichier et la campagne privée. Un worker actif interdit reprise et abandon
grâce au même verrou de session. L'abandon exige une confirmation et libère la
file, mais conserve les artefacts jusqu'au nettoyage explicite.

Source introuvable : vérifier PVC, chemin et montage, puis restaurer **exactement**
le fichier original sous `UUID/propositions.jsonl`. La taille et l'empreinte
seront revérifiées. Espace insuffisant : étendre le volume selon les capacités
du CSI ou nettoyer uniquement des jobs terminaux expirés. Ne jamais remplacer
le fichier d'un job par un fichier corrigé : créer un nouvel import.

```sh
# Depuis la racine ; dry-run par défaut.
uv run python app-suivi-reconciliation/manage.py cleanup_matching_jobs
uv run python app-suivi-reconciliation/manage.py cleanup_matching_jobs --apply
```

Seuls les jobs terminaux non actifs et expirés sont concernés. Les jobs
`RETRYABLE`/`INTERRUPTED` sont conservés même anciens. La commande garde l'historique
du job, efface les seules données de campagne non publiée et ses index de staging,
puis les fichiers sous la racine vérifiée. Elle refuse un chemin résolu extérieur.
Les campagnes publiées, leurs décisions et le PVC sont conservés.

Rollback applicatif : arrêter le worker, conserver base, PVC et migration
additive, puis restaurer le précédent Deployment compatible. Ne jamais exécuter
une migration inverse pour récupérer un import. Un ancien binaire ne doit pas
reprendre un job de protocole 1 ; garder ses sources/checkpoints et revenir au
binaire compatible pour le reprendre, ou l'abandonner explicitement.

## Tests et portabilité Clever Cloud

Les réglages `config.import_test_settings` isolent les tests du `.env` métier.

```sh
uv run python app-suivi-reconciliation/manage.py test \
  imports_app.test_resumable imports_app.test_job_actions imports_app.test_jobs \
  imports_app.test_postgres_import reconciliation.test_campaigns \
  --settings=config.import_test_settings --noinput
# Pour PostgreSQL : IMPORT_TEST_POSTGRES=1, IMPORT_TEST_HOST/PORT/DB/USER/PASSWORD
# doivent désigner une base de test dédiée avec droit de créer la base test_*.
```

Les tests incluent commits réels, exceptions avant/après commit, annulation de
publication, décision pendant le staging, source corrompue/absente, doublons
inter-lots, v3/Sage optionnel, permissions/CSRF, migration historique et rétention.
Sur PostgreSQL, ils couvrent aussi deux sessions/workers, perte de session et
processus tué avant/après commit. Le poste actuel exécute les scénarios SQLite ;
les tests réservés à PostgreSQL sont explicitement sautés si ce backend manque.
La CI et la recette Onyxia restent nécessaires : aucun résultat distant n'est
présumé, ni aucun benchmark 1,6 Go annoncé sans mesure.

### Bilan des vérifications locales

| Vérification exécutée | Résultat |
| --- | --- |
| Suite complète Django depuis `app-suivi-reconciliation`, réglages de test isolés | 515 cas : 500 réussis, 15 ignorés |
| Sélection finale imports/checkpoints/actions/campagnes, incluant les cas ajoutés après la suite complète | 68 cas : 51 réussis, 17 ignorés faute de PostgreSQL |
| Moteur : `.venv/Scripts/python.exe -m pytest -q` | 341 réussis, 2 ignorés |
| `manage.py check` | Aucune erreur |
| `makemigrations --check --dry-run` | Aucun changement de modèle non migré |
| `git diff --check` | Aucune erreur de whitespace |

Ces sélections se recouvrent et ne s'additionnent pas. Les deux échecs initiaux
de statistiques SQLite dus à un réglage de test ont été corrigés en conservant
la configuration automatique normale. Le scénario v3 vérifie aussi l'historique
BAP ; une comparaison supplémentaire avec le chemin atomique couvre les tiers
ODS absents, les contrôles, l'inventaire Sage et les signatures normalisées hors
identifiants techniques. Les changements finaux de fencing PostgreSQL sont
couverts par des scénarios réservés à ce backend, à exécuter dans la CI.

Fichiers principaux : `imports_app/{models,jobs,resumable,views,urls,context_processors}.py`,
migration `0004_durable_checkpoints`, commandes `matching_worker`,
`run_matching_job`, `cleanup_matching_jobs`, adaptation commune de `campaigns.py`,
configuration et templates de suivi/bannière, tests de reprise et d'actions,
workflow PostgreSQL et manifests Deployment/PVC/migrations par environnement.
Le guide PostgreSQL existant renvoie à ce document. Aucun secret, PVC ou jeu de
données métier n'a été modifié sur l'infrastructure.

Restent à exécuter : workflow PostgreSQL réel, bootstrap/migration DEV avec le
nouveau tag d'image, recette de mort/recréation du pod, mesure sur 1,6 Go, puis
recette PREPROD. Docker n'est pas démarré et aucun contexte Kubernetes n'est
configuré sur le poste. Aucun déploiement, aucune migration distante et aucune
action PROD n'ont été réalisés.

Le cœur du traitement est indépendant du déclenchement : `run_job()` consomme
au plus un job et `matching_worker` n'est qu'une boucle supervisée. La commande
one-shot sans UUID est prête pour un futur runner par tâche. Avant Clever Cloud,
il faudra définir le stockage durable partagé ou objet, une identité immuable
et une lecture avec accès par offset/cache local, le déclenchement et la politique
de retries des tâches. Aucun déploiement Clever Cloud ni hypothèse sur son
stockage/scheduling n'est implémenté ici. Celery et Redis ne sont pas ajoutés.
