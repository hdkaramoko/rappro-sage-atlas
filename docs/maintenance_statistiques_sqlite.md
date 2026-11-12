# Maintenance des statistiques SQLite — 9 novembre 2026

## Intégration et risque transactionnel

`import_bundle` est atomique ; `import_campaign` y prépare historiquement le
cadrage avant le commit. Un `ANALYZE` placé juste avant ce calcul resterait
dans la transaction d'import : ce point n'a pas été retenu.

Le circuit utilisé par le worker et la commande d'import **SQLite sur fichier**
dispose déjà d'une copie privée et d'une publication atomique. Il suit désormais :

1. Importer, valider et committer le JSONL **sur la copie**, en différant seulement
   la préparation du cadrage. Décisions, contrôles et reprises restent identiques.
2. Actualiser les statistiques de la copie, hors transaction englobante.
3. Préparer le cadrage sur cette copie avec les mêmes règles. Tout échec à ces
   deux étapes empêche la publication et conserve la campagne active.
4. Transférer les résultats, y compris `AccountingGroup` et `AccountingProject`,
   avec les autres photographies cachées, puis publier selon le protocole atomique
   existant et ses contrôles de révision. Les enfants sont nettoyés avant les
   parents lors de la reprise d'un staging interrompu.
5. Actualiser les statistiques de la base publiée, après commit. Les statistiques
   internes SQLite ne sont pas transférées avec les tables applicatives : les
   deux collectes concernent donc deux bases distinctes, pas deux maintenances
   concurrentes sur une même base.

**La bascule de campagne, l'atomicité de publication et ses conditions de fraîcheur
sont préservées.** Les synthèses ne deviennent pas visibles avant leurs contrôles.
Les imports historiques v1 sans campagne et les réimports identiques ne préparent
pas artificiellement une campagne ni ses agrégats.

Pour un appel **direct** à `import_bundle`, la préparation reste dans sa transaction
existante. La maintenance est enregistrée via `transaction.on_commit`, annulée
sur rollback et exécutée synchroniquement par le processus qui committe. Cette
voie ne bénéficie pas de statistiques nouvelles avant sa toute première
préparation interne ; pour les gros imports SQLite, utiliser la commande/worker
sur copie privée. PostgreSQL garde son séquencement actuel, sans maintenance
automatique spécifique. Cette limite évite de déplacer implicitement la publication
ou de rendre un import direct partiellement visible.

## Politique de maintenance

Service : `reconciliation.sqlite_statistics.maintain_statistics`.

- **SQLite uniquement**, vérifié par vendor et moteur Django. PostgreSQL et les
  autres moteurs retournent `skipped/backend_not_sqlite` avant tout SQL SQLite.
- Avant `prepare_accounting` autonome : collecte seulement si les statistiques
  des tables utiles sont absentes. Vérifications sur `sqlite_master`, `sqlite_stat1`
  et au besoin `SELECT 1 … LIMIT 1`, sans décompte des grandes populations.
- Après chaque nouvelle campagne complète SQLite committée : actualisation.
  Ce choix est volontairement simple ; le coût mesuré de la collecte est faible
  et aucune variation de volume “optimale” n'a été inventée.
- Une table vide n'a pas besoin d'entrée statistique : des appels répétés sur une
  base vide ne provoquent pas de collecte permanente.
- Aucune maintenance dans `refresh_project`, correction, confirmation, refus,
  annulation, consultation ni recalcul ciblé.

Configuration : **`SQLITE_STATISTICS_AUTO=true` par défaut**. Mettre `false`
désactive les déclenchements automatiques, sans empêcher la commande explicite
ou le forçage volontaire. La préparation privée reste séparée de sa transaction
d'import même lorsque l'automatisme est désactivé.

Le service emploie **ANALYZE**, stratégie réellement mesurée. Aucun `PRAGMA optimize`,
nouvel index, seuil arbitraire, modification de journalisation/durabilité ou
nouveau modèle n'est introduit.

## Transactions, concurrence et erreurs

Une transaction Django active, un autocommit désactivé ou une transaction SQLite
manuelle existante produit `deferred/active_transaction`, sans ANALYZE. Le service
prend ensuite un **BEGIN IMMEDIATE**, revérifie les statistiques sous ce verrou,
collecte puis committe. SQLite sérialise ainsi les maintenances avec les autres
écrivains ; les timeouts existants sont conservés. Un concurrent qui vient de
collecter évite une seconde analyse conditionnelle. Un forçage explicite peut
collecter de nouveau, mais toujours séquentiellement.

En cas d'erreur SQL, le service rollbacke sa seule transaction, libère le verrou
et retourne `failed` avec le code SQLite disponible (par exemple `SQLITE_BUSY`)
ou la classe d'erreur. Les logs ne contiennent ni SQL,
paramètre, code projet, montant, chemin de base ni traceback sensible.

- Préparation autonome : maintenance échouée/reportée → arrêt explicite avant calcul.
- Copie privée : échec → aucune publication.
- Base déjà publiée ou import direct déjà committé : l'échec est journalisé,
  **sans prétendre annuler les données validées**. La maintenance n'est pas rejouée
  automatiquement. Une interruption du processus avant le callback nécessite
  une relance explicite ; aucun ordonnanceur implicite n'a été ajouté.

Le logger `reconciliation.sqlite_statistics`, niveau INFO sur console, expose
`status`, `reason`, `backend`, `seconds` ; erreurs au niveau ERROR. Les phases du
worker distinguent collecte privée et collecte après publication. Les quatre
états d'exploitation sont `executed`, `skipped`, `deferred`, `failed`.

## Exploitation

Depuis `app-suivi-reconciliation` :

```powershell
# Vérifier / collecter si nécessaire, sans préparer les agrégats
python manage.py maintain_sqlite_statistics

# Actualisation volontaire, même si les statistiques existent
python manage.py maintain_sqlite_statistics --force

# Préparation habituelle : maintenance conditionnelle puis progression
python manage.py prepare_accounting

# Forçage de collecte avant préparation explicite
python manage.py prepare_accounting --force-statistics
```

La commande de maintenance accepte également `--database ALIAS`, limité aux
connexions configurées. `prepare_accounting --campaign ID` reste disponible ;
aucune campagne historique n'est reconstruite automatiquement.

La progression affiche `0/total`, puis le compteur et le temps écoulé après chaque
projet, avec sortie flushée, et un bilan final. Elle ne révèle aucun code projet.
L'état de maintenance est affiché avant le calcul, avec motif et durée.

Pour les imports volumineux :

```powershell
python manage.py import_review_bundle chemin/vers/campagne.jsonl
```

SQLite sur fichier utilise la copie privée ; PostgreSQL reste sur son circuit
transactionnel normal. Aucun ANALYZE automatique PostgreSQL : vérifier ses plans
et la maintenance native sur cet environnement avant de conclure sur ses délais.

## Tests et mesures

Tests dédiés :

```powershell
python manage.py test reconciliation.test_sqlite_statistics imports_app.test_sqlite_staging --noinput
```

Ils vérifient collecte réelle sur SQLite, statistiques déjà présentes, forçage,
désactivation, ignorance PostgreSQL, transaction active, concurrence simulée
après prise du verrou, rollback d'une collecte échouée, erreurs sans données
sensibles, callback après commit/annulé sur rollback, conservation d'un import
committé, progression, résultats comptables et absence d'appel depuis les actions.

Les scénarios disque exercent la séquence commit privé → maintenance → cadrage
→ publication, le transfert des synthèses, l'annulation en cas d'erreur sur copie,
la reprise de staging, les anciens formats et les protections de concurrence.

La comparaison sur copie réelle et les résultats finaux sont consignés à la fin
de ce document. La base utilisateur n'est pas utilisée pour les benchmarks.

## Fichiers et portée

- `reconciliation/sqlite_statistics.py` : service, contexte privé et callback.
- `reconciliation/campaigns.py` : débranchement privé et enregistrement après commit.
- `imports_app/sqlite_staging.py` : séquence privée, transfert/nettoyage des synthèses.
- `reconciliation/management/commands/prepare_accounting.py` : maintenance et progression.
- `reconciliation/management/commands/maintain_sqlite_statistics.py` : exploitation explicite.
- `config/settings.py` : configuration et logger ciblé.
- `reconciliation/test_sqlite_statistics.py`, `imports_app/sqlite_scenarios.py` : tests.

Aucune migration, régénération JSONL, modification de règle comptable, signe,
rapprochement, auto-validation, décision ou persistance intercampagnes.

## Résultats de validation

- Suite complète : **334 tests exécutés, 3 ignorés**, succès en 213 s.
- Les **12 tests dédiés de maintenance** ont été rejoués après ajout des cas
  de verrouillage/rollback et erreur inattendue de callback : tous réussis.
- Les scénarios SQLite sur disque de la suite vérifient notamment les deux
  nouveaux cas de séquencement et de conservation de la campagne active.
- `makemigrations --check --dry-run` : aucun changement de modèle.
- `git diff --check` : aucune erreur.

Une copie isolée de la base représentative de l'audit précédent a été réutilisée.
Les statistiques ont été retirées **uniquement sur cette copie**, puis la nouvelle
commande `prepare_accounting` a été exécutée telle quelle, sans changer ses calculs.

| Mesure | Résultat |
|---|---:|
| Campagne préparée | 1 613 projets |
| Durée totale de commande, maintenance incluse | **99,446 s** |
| Collecte ANALYZE, temps execute | **6,047 s** |
| Maintenance complète affichée, verrou/commit inclus | **6,049 s** |
| Préparation affichée après maintenance/comptage | **92,98 s** |
| Exécutions SQL de la commande | 26 273 |
| Temps CPU | 89,203 s |
| Pic mémoire approximatif du processus | 81,82 Mio |
| Contrôle conditionnel suivant | ignoré, `statistics_present`, 0,0004 s |

Les sept projets de comparaison prennent **73,201 s sans statistiques**, puis
**1,491 s après**. Le premier projet du passage initial prend à lui seul 32,326 s :
les caches système ne sont pas maîtrisés. Il ne faut pas attribuer toute cette
différence à la maintenance ni comparer ces temps directement aux 82–85 s de
l'audit précédent, réalisé dans d'autres conditions de cache. Le nouveau passage
est sous `DEBUG=False` ; ces mesures ne prédisent pas PostgreSQL ni la durée
complète d'un import, dont la transaction et les autres étapes diffèrent.

Les plans des requêtes critiques confirment le changement attendu :

| Requête | Avant collecte | Après collecte |
|---|---|---|
| Collisions Sage | index référence filtré sur campagne seule | index campagne/projet/pièce filtré sur campagne **et projet** |
| Contrôles | index unique campagne/clé, filtre campagne seule | index campagne/projet + tri local |
| Atlas | index campagne seule | index projet, puis vérification du périmètre |

L'empreinte des résultats des **1 613 projets et 307 367 groupes** reste identique :
`6593f3116b1b8fbb52695d0985774cd964822c41f546dfd40efd392a1a467150`.
Les dates et PK de projection sont exclues ; tous les champs comptables, types
et motifs sont inclus. Les compteurs de progression vont de 0/1613 à 1613/1613.

[Mesures et plans anonymisés](maintenance_statistiques_validation.json).
L'[inventaire des docstrings](maintenance_statistiques_docstrings.md) couvre les
fonctions et classes nouvelles/modifiées. PostgreSQL n'était pas disponible pour
une mesure réelle ; le garde-fou backend est testé par mock. Aucune maintenance
n'a été exécutée sur la base utilisateur pendant le développement.
