# Mode maintenance administrable Atlas × Sage X3

## Intégration et autorisations

L’Administration existante est Django Admin (`/admin/`). La propriété
`User.is_global_admin` correspond actuellement à `is_superuser or is_staff` :
elle ouvre aussi des fonctionnalités métier et ne constitue donc pas une
permission de maintenance.

Le pilotage exige simultanément un compte authentifié, actif, **staff**, et la
permission Django **`maintenance.change_maintenancestate`**. Un superutilisateur
staff possède cette permission implicitement. Un compte staff seul, un accès
global aux projets ou la validation métier ne suffisent pas. La permission
`view_maintenancestate` seule ne suffit pas non plus.

Pour déléguer, un administrateur des comptes attribue explicitement la permission
de modification « maintenance de l’application » au compte staff ou à son groupe.
Cette évolution ne modifie ni les rôles existants ni leurs droits métier.

## Utilisation

Dans **Administration → Maintenance → Maintenance de l’application**, le panneau
affiche l’état courant, sa dernière modification et les vingt derniers changements.

1. **Normal** : fonctionnement habituel, état initial après migration.
2. **Programmée / avertissement** : saisir le message et éventuellement le début
   prévu. Le bandeau apparaît sur les pages authentifiées, y compris Admin. Les
   consultations et actions restent possibles. Une date passée n’active rien.
3. **Active** : sélectionner cet état et cocher la confirmation explicite. Après
   sauvegarde, les nouvelles requêtes métier sont bloquées, même celles des
   administrateurs. Le panneau reste accessible aux comptes autorisés.
4. **Normal** : enregistrer cet état pour rouvrir immédiatement les accès.

Tout enregistrement à l’état Active exige la confirmation. Les dates sont
informatives : elles indiquent un début, jamais une heure garantie de reprise.
Aucun en-tête `Retry-After` n’est inventé.

Chaque sauvegarde et son audit sont atomiques : ancien/nouvel état, acteur,
horodatage, message et début prévu. L’audit conserve le nom de l’acteur si le compte
est ensuite supprimé. Il n’existe pas d’édition ou de suppression de l’audit dans
l’interface. Un numéro de version empêche un ancien formulaire d’écraser une
modification concurrente ; il faut alors recharger le panneau.

## Blocage HTTP et sessions

Le middleware est placé **après SessionMiddleware et AuthenticationMiddleware,
avant CsrfViewMiddleware et les vues**. Il connaît donc l’utilisateur et peut
retourner 503 avant l’analyse d’un formulaire métier. Les vues autorisées gardent
leur protection CSRF normale ; le pilotage exige POST, permission et confirmation.

Le middleware de session est une sous-classe minimale de celui de Django. Pour
une panne de configuration, la sonde de vie et les assets locaux uniquement, il
ne touche pas à la session en sortie de réponse : Django tenterait sinon de lire
son expiration, même pour un 503, ce qui pourrait recréer une erreur 500 en cas
de panne totale avec un cookie existant. Aucun cookie n'est effacé par ce secours.

Le middleware effectue une seule petite lecture de configuration par requête dynamique,
sans cache entre workers et sans écriture de configuration à la consultation.
Tous les workers utilisant la même base relisent le même état validé. Un worker
dont la requête a déjà franchi ce contrôle est une opération en cours.
Le panneau relit également l’état pour afficher sa valeur courante et son audit.

En Active, GET, POST, PUT, PATCH, DELETE, HEAD et OPTIONS sont bloqués sur les
parcours métier, les imports, les URL inconnues et les éventuelles API. Une page
ouverte avant activation ne permet pas d’envoyer un nouveau POST métier.
Les exceptions sont limitées aux routes résolues suivantes :

- le panneau de maintenance et l’index Admin, pour les gestionnaires autorisés ;
- `/maintenance/access/`, formulaire de récupération administrative protégé CSRF ;
- les véritables ressources statiques servies par WhiteNoise, ou la vue statique
  Django locale pour GET/HEAD ; aucun préfixe d’API n’est exempté ;
- `/health/live/`, uniquement GET/HEAD : **sonde de vie du processus Django**, sans
  lecture de base. `{"status":"alive"}` ne signifie pas que les fonctions métier
  sont ouvertes ou que PostgreSQL est disponible. Aucun manifeste n’est modifié.

Le formulaire de récupération retourne 503 aux visiteurs et aux tentatives
refusées. Il ne crée une session qu’après authentification d’un gestionnaire
autorisé, puis redirige exclusivement vers le panneau. Les autres écrans Admin
et les imports restent bloqués, même pour ce gestionnaire.

La page 503 est autonome et responsive : marque textuelle, CSS intégré, message
échappé et aucune donnée de campagne, aucun processeur de contexte susceptible
de lire la base, aucun fichier statique requis pour son rendu.

Aucune session n’est supprimée et aucune déconnexion n’est imposée. La politique
de session existante reste applicable, notamment l’expiration après dix minutes
sans activité : une session encore valide retrouve ses accès à la réouverture,
une session expirée nécessite une nouvelle connexion.

## Travaux longs et récupération

**Vérifier la fin des traitements avant toute migration ou intervention lourde.**
Le panneau rappelle cette consigne. Le middleware n’annule pas les requêtes déjà
entrées ni leurs transactions.

Les imports HTTP existants lancent un processus détaché `run_matching_job` : un
processus déjà lancé continue et peut terminer son import pendant la maintenance.
Leur écran de suivi métier est également bloqué en Active ; consulter leur suivi
avant activation ou les journaux côté serveur pendant la maintenance.
Les commandes `import_review_bundle`, `prepare_accounting`, de statistiques et
les autres commandes d’exploitation restent exécutables depuis le serveur. Elles
ne passent pas par HTTP et ne sont ni stoppées ni annulées artificiellement.

Si la session administrative a expiré, utiliser `/maintenance/access/`. Si aucun
compte autorisé n’est disponible, l’exploitation disposant d’un accès au serveur
peut exécuter depuis `app-suivi-reconciliation` :

```powershell
python manage.py maintenance_normal --reason "Récupération après incident"
```

Cette commande remet Normal, efface le message et le début annoncé et ajoute un
événement « Exploitation serveur » avec le motif obligatoire. Elle n’est exposée
par aucune route HTTP. Ne pas inclure d’informations sensibles dans le motif.
Une base indisponible empêche aussi cette commande : rétablir la base, appliquer
les migrations nécessaires puis réessayer.

## Installation et erreurs de configuration

Depuis `app-suivi-reconciliation`, avec l’environnement et la base du déploiement :

```powershell
python manage.py migrate
python manage.py collectstatic --noinput
```

La migration `maintenance/0001_initial.py` crée deux petites tables et initialise
la ligne singleton à Normal. Aucune migration n’est appliquée automatiquement
par une requête. Les tests utilisent uniquement une base jetable ; la base locale
de travail n’est pas migrée par l’implémentation.

Une ligne absente dans une table existante vaut Normal, sans création implicite
en lecture. Une table absente, un verrou ou une indisponibilité de la base lors
de la lecture produit au contraire un **503 explicite**, avec erreur journalisée
dans `maintenance.middleware`. Cela évite de présenter l’application comme ouverte
alors que son état ne peut pas être vérifié. Après migration/rétablissement,
la requête suivante relit la configuration ; aucun verrou en mémoire ne persiste.

Un échec de transition est signalé dans le panneau et journalisé, sans annoncer
faussement son succès. Si l’audit échoue, la transition est annulée. La page de
secours ne dépend pas des tables utilisateur, de campagne ou d’audit pour son rendu.

Ce mécanisme suppose que Django répond. Une panne du processus ou de la base
ne remplace pas une page de maintenance au niveau du proxy/ingress. Aucune
configuration de proxy, ordonnanceur, Redis ou Celery n’est ajoutée.

## Fichiers et validation

- `maintenance/models.py`, `services.py`, `forms.py` : singleton, audit, droits,
  transitions atomiques et confirmation.
- `maintenance/middleware.py`, `views.py`, `admin.py` : garde HTTP, récupération,
  sonde de vie et panneau Admin.
- `maintenance/management/commands/maintenance_normal.py` : récupération serveur.
- `maintenance/migrations/0001_initial.py` : tables et initialisation Normal.
- `maintenance/tests.py` : tests de permissions, HTTP, sessions, audit, concurrence
  de versions, configuration absente/indisponible, récupération, statiques et
  fraîcheur logique entre deux instances de middleware.
- `reconciliation/test_accounting.py`, `test_journey.py`, `test_ui.py` : les tests
  de coût vérifient exactement une lecture de maintenance et conservent leur
  budget SQL métier précédent.
- `config/settings.py`, `config/urls.py` : application, middleware et routes.
- `templates/maintenance/*`, `templates/admin/base_site.html`, `templates/base.html` :
  interface de pilotage, bandeaux et pages autonomes.
- README racine et application : liens vers ce guide.

Les tests de collecte statique utilisent un dossier temporaire, y compris le
stockage WhiteNoise avec manifeste et `DEBUG=False`. La compatibilité multi-workers
est vérifiée logiquement avec deux instances indépendantes lisant le même état.
La solution utilise l’ORM et des mises à jour conditionnelles, sans SQL spécifique.
Les essais PostgreSQL réels nécessitent une instance de test dédiée ; ils ne sont
pas remplacés par les essais SQLite et ne sont pas annoncés comme exécutés.

### Résultats locaux du 11 novembre 2026

- `python manage.py test maintenance --noinput` : **17 tests réussis**.
- `python manage.py test --noinput` : **388 tests recensés, 385 réussis et
  3 ignorés**, en 166,750 s. Les trois cas ignorés exigent PostgreSQL : import,
  réservations concurrentes et verrouillage de lignes. Aucun serveur PostgreSQL
  de test n’a été utilisé ; le multi-workers est testé logiquement, pas par un
  déploiement réel de plusieurs processus.
- `python manage.py makemigrations --check --dry-run` : aucune migration manquante.
- `python manage.py check` : aucune anomalie.
- Ruff, règles F sur le nouveau module et la configuration : réussi.
- Vérification des docstrings de toutes les classes et fonctions du nouveau
  module : réussie ; `git diff --check` : aucune erreur d’espacement.
- Liste de cadrage de 120 projets / 12 000 groupes : 0,027 s et 15 requêtes,
  dont une lecture de maintenance. Le budget métier précédent est conservé.
- La collecte statique avec manifeste WhiteNoise est vérifiée en dossier
  temporaire. Aucune migration, activation ou réécriture de campagne n’a été
  exécutée sur la base de travail.

L’avertissement habituel sur l’absence du dossier local `staticfiles/` apparaît
pendant la suite ; la collecte dédiée en dossier temporaire réussit.
