# Imports volumineux sous SQLite

## Problème et objectif

Le fichier JSONL peut contenir plusieurs centaines de milliers d'enregistrements.
Auparavant, `run_job()` et `import_bundle()` conservaient une transaction sur la
base applicative pendant la lecture, les contrôles et les écritures ORM. En mode
SQLite `DELETE`, cette longue écriture pouvait finir par bloquer même la lecture
d'une session : la page de suivi affichait `database is locked` alors que le
worker poursuivait son traitement.

Le correctif sépare **préparation**, **chargement invisible** et **publication**.
La campagne précédente reste consultable ; le métier ne voit jamais une campagne
partielle. Le moteur de rapprochement reste indépendant de l'application.

## Parcours technique

1. Le navigateur transfère le fichier et attend la fin de son enregistrement.
   Cette première partie reste synchrone. Ensuite, `launch()` démarre un processus
   indépendant, sans fenêtre de terminal sous Windows.
2. `worker_lock()` réserve l'import à un seul processus. Le SHA-256 et les doublons
   sont contrôlés. La contrainte `MatchingJob.active` complète ce verrou système.
3. `staged_import()` active WAL, nettoie par lots les restes **non publiés** d'un
   précédent échec, puis crée `preparation.sqlite3` avec l'API SQLite `backup()`.
   Une simple copie de `db.sqlite3` aurait pu oublier des pages présentes dans WAL.
4. `private_database()` redirige temporairement la connexion Django du worker vers
   cette copie. `import_bundle()` y réalise les contrôles, comparaisons de campagnes,
   reports de validations et calculs de multiples habituels. Son décorateur
   `@transaction.atomic` protège désormais cette préparation isolée. Il ne garde
   plus le verrou de la base utilisée par les utilisateurs pendant ces calculs.
5. Après contrôle de fin de fichier et nouvelle vérification du SHA-256, la copie
   est attachée à une connexion SQL dédiée. Les nouvelles campagnes sont créées
   avec `published=False`. Inventaire, preuves des groupes et contrôles de multiples
   sont transférés par `INSERT … SELECT`, en transactions de **500 lignes au plus**.
6. Une dernière transaction applique les sources et revues courantes, les archives
   de décision et les contributions, puis publie la campagne et le succès du job.
   Ces modifications sont des opérations SQL ensemblistes, sans boucle de `save()`
   sur la base réelle. Un échec de cette transaction annule toute la bascule.

La base réelle n'est jamais remplacée par le fichier temporaire. Comptes,
sessions et portefeuilles ne sont pas recopiés par-dessus leurs versions vivantes.
Les modèles métier et les identités des lignes restent les mêmes.

## Pourquoi ces classes et ces protections ?

| Élément | Problème résolu et choix |
| --- | --- |
| `PublishedCampaignManager` | Masque les campagnes préparées dans les listes et les recherches de campagne précédente. Les vues d'inventaire, de multiples et l'administration filtrent aussi les données non publiées. |
| `ImportRevision` et triggers de la migration 0011 | Détectent une mutation métier venant de n'importe quel processus, dans la transaction de cette mutation. Un compteur Python en mémoire ne protégerait pas contre une validation faite par le serveur. |
| `write_batch()` | Prend le verrou SQLite avec `BEGIN IMMEDIATE` **avant** la lecture du compteur ; évite une course entre vérification et écriture. Mesure chaque transaction et garantit son rollback en cas d'exception. |
| `private_database()` | Le gestionnaire de contexte restaure la connexion d'origine dans `finally`, y compris après fichier invalide. Il est réservé au worker mono-utilisateur, hors transaction Django. |
| `ImportProgress` | Écrit les phases, compteurs et durées sur disque : aucun second écrivain SQLite n'est créé pour le suivi. `progress.json` est remplacé atomiquement et `import.log` garde les événements. |
| `import_control_batch()` | Charge inventaire et anciens arbitrages en deux lectures par lot, puis utilise `bulk_create`. Les contraintes SQL détectent aussi les doublons entre lots. Les contrôles métier sont conservés. |

La préparation mémorise la révision de sa copie. Chaque transaction de chargement
et la publication comparent la révision réelle attendue. Les écritures propres à
l'import mettent à jour cette valeur attendue **dans leur transaction**.

Si une personne valide, refuse, commente ou modifie une donnée métier pendant la
préparation, la publication est refusée : la nouvelle décision reste intacte et
il faut relancer l'import pour la prendre en compte. Il n'y a pas de fusion
automatique de deux décisions. Le contrôle est volontairement global : une
modification d'un autre projet peut également imposer cette relance. Les écritures
de sessions, `last_login` et les changements de portefeuille ne l'invalident pas.

## WAL et limites

WAL permet aux lecteurs de continuer pendant une écriture. Le délai d'attente des
connexions est fixé à 30 secondes pour absorber une contention brève. Ces mesures
complètent la séparation des phases ; augmenter le délai seul n'aurait pas résolu
le problème initial.

SQLite conserve **un seul écrivain à la fois**. La transaction de publication
finale n'est pas découpée : elle conserve le « tout ou rien » des projections
visibles. Sa durée dépend du nombre de sources et revues à mettre à jour ; elle
peut encore retarder des décisions ou des écritures de session. Le journal mesure
cette durée. Aucune garantie de temps n'est donnée pour les 467 832 lignes réelles
sans mesure de leur import avec cette version.

La lecture JSONL est progressive, mais certains ensembles de clés et les candidats
au report restent en mémoire. Les propositions continuent d'utiliser leur logique
ORM dans la copie privée : cette étape peut rester longue, sans verrouiller la
base réelle. Les contrôles de multiples et les copies vers la base réelle sont
traités en lots. PostgreSQL et les bases de test en mémoire conservent le parcours
atomique habituel ; ce correctif n'est pas une migration de moteur SQL.

WAL nécessite un stockage local adapté, partagé par les processus de la même
machine. Ne pas déplacer la base sur un partage réseau pour organiser les imports.

## Supervision, disque et reprises

Dans `var/matching/<identifiant>/` :

- `propositions.jsonl` : fichier reçu, conservé avec son empreinte ;
- `preparation.sqlite3` : copie privée préparée, pouvant contenir toute l'histoire
  applicative ; elle n'est jamais proposée au téléchargement par l'application ;
- `progress.json` : dernière phase et compteurs, lus par la page de suivi ;
- `import.log` : phases horodatées, durées totales et `transaction_seconds` ;
- `heartbeat` : signal de vie toutes les 10 secondes, distinct de l'avancement ;
- `worker.log` : sortie du processus.

La page s'actualise toutes les 5 secondes. Les compteurs sont propres à chaque
phase : pages copiées, lignes d'inventaire, groupes ou contrôles. Ce n'est pas un
pourcentage global. Une phase sans nouvelle mesure ne signifie pas nécessairement
que le processus est arrêté.

Sous Windows, une lecture concurrente ou un antivirus peut empêcher temporairement
le remplacement de `progress.json` (`WinError 5`). Le suivi tente trois remplacements,
avec deux attentes de 50 ms au maximum. En cas d'échec, le dernier JSON complet est
conservé, un avertissement est ajouté au journal si possible et la mesure suivante
réessaie. Une erreur d'accès au JSON ou au journal n'interrompt jamais l'import ;
les erreurs sur les données et la base continuent, elles, à être bloquantes.

Un contrôle préalable exige au moins `2 × taille de la base + 3 × taille du JSONL`
d'espace libre dans le répertoire de travail. C'est une marge, pas une borne
garantie : index, historique et WAL peuvent demander davantage. La copie de
préparation est conservée après traitement pour diagnostic et doit entrer dans
la politique de rétention des dossiers d'import. Ne supprimer une copie privée
qu'après avoir vérifié que son worker ne fonctionne plus ; ne jamais supprimer
les fichiers `db.sqlite3-journal`, `db.sqlite3-wal` ou `db.sqlite3-shm` pour
« déverrouiller » la base.

En cas de fichier invalide, la campagne courante reste intacte. En cas d'arrêt
pendant le chargement, les lots incomplets restent invisibles. Le lancement suivant
les nettoie avant de reprendre **depuis le début**, sans reprendre à mi-fichier.
Un job interrompu encore actif peut être repris avec :

```powershell
uv run python manage.py run_matching_job <identifiant> --resume
```

Un job `FAILED` doit être soumis à nouveau via l'interface. Un import déjà publié
avec succès est reconnu par son SHA-256 et ne crée pas une campagne supplémentaire.
Une erreur d'écriture du journal après publication ne transforme pas le succès
en échec dans la base.

## Activation sur une installation existante

Dans `app-suivi-reconciliation`, **après la fin de l'ancien import** et avant de
relancer le serveur avec le nouveau code :

```powershell
uv run python manage.py prepare_sqlite_imports --migrate
uv run python manage.py runserver
```

La première commande prend le verrou des workers, effectue une sauvegarde SQLite
cohérente dans `var/backups/`, applique les migrations puis active WAL. Elle refuse
de continuer si un import détient encore le verrou ; elle ne tue aucun processus.
La migration 0011 marque les campagnes existantes comme publiées et ajoute les
triggers de révision. Sans `--migrate`, la commande vérifie la migration déjà
appliquée et active seulement WAL.

Un worker déjà démarré continue d'exécuter l'ancien code : modifier les fichiers
Python ne corrige pas rétroactivement sa transaction. Ne pas exécuter `migrate`
séparément en plein import pour contourner le refus de la commande protégée.

## Vérifications automatisées

`imports_app.test_sqlite_staging` lance un processus indépendant sur des bases
SQLite temporaires réellement stockées sur disque. Huit scénarios couvrent :

- 501 groupes, plusieurs lots, ancienne campagne visible et validation reportée ;
- mutation concurrente détectée, décision conservée et nettoyage à la relance ;
- panne au milieu de la publication, rollback puis reprise ;
- fichier tronqué rejeté sans mutation des données visibles ;
- succès du worker et doublon sans nouvelle campagne ;
- archive v1, campagnes v3, contributions et égalité entre résultat préparé/publié ;
- lecture depuis une seconde connexion pendant une transaction WAL ouverte.
- activation avec sauvegarde, migration et refus si un worker détient le verrou.

Les tests métier existants complètent ces scénarios. Aucun de ces tests n'utilise
la base ni les extractions réelles de l'administrateur.

Vérification du 28 septembre 2026 : suite Django complète, 81 tests réussis et
1 test de concurrence PostgreSQL ignoré sous SQLite. Les huit scénarios disque
sont exécutés par l'un de ces tests. Ruff et la vérification de cohérence des
migrations passent également.
