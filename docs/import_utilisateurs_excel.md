# Import Excel des utilisateurs

## Accès et parcours

Ouvrir **Administration → Comptes → Utilisateurs → Importer des utilisateurs**.
Un bouton figure également à l’accueil de l’Administration, notamment pour les
comptes autorisés à créer des utilisateurs sans droit de consulter leur liste.
Le bouton est présent dans la liste des utilisateurs pour les administrateurs
autorisés. La route est également accessible sous
`/admin/accounts/user/import-excel/`.

Le droit requis est celui déjà fourni par Django : **`accounts.add_user`**, sur
un compte authentifié, actif et staff. Les superutilisateurs staff le possèdent
implicitement. `is_staff`, `is_global_admin` ou les droits de validation métier
ne suffisent pas seuls. Aucun rôle ou permission supplémentaire n’est créé.

1. Sélectionner le classeur `.xlsx`, puis **Contrôler et afficher l’aperçu**.
2. Lire l’aperçu : numéros de lignes, noms, prénoms, identifiants et comptes
   déjà présents. Aucun mot de passe n’y apparaît.
3. Si le classeur est valide, **sélectionner de nouveau le même fichier**, puis
   **Confirmer l’import**. Le serveur ne conserve pas le fichier entre étapes.
4. Lire le bilan : lignes créées et lignes ignorées car déjà présentes.
5. Attribuer les projets avec **Importer des portefeuilles**, qui reste inchangé.

Message affiché : « Comptes créés sans portefeuille ; attribuez ensuite les
périmètres depuis Importer des portefeuilles. »

## Format exact

Le fichier réel `users_mdp.xlsx` n’est ni modifié ni inclus dans les tests. Les
tests génèrent un classeur synthétique en mémoire de la même structure.

- Feuille : **`data`**, avec cette casse.
- Ligne 1 : **`nom`, `prénom`, `username`, `mdp`**, dans cet ordre et sans colonne
  supplémentaire. Les autres feuilles ne sont pas importées.
- Un utilisateur par ligne ; les quatre cellules doivent contenir du texte
  non vide. Les lignes entièrement vides sont ignorées.
- Les noms/prénoms sont débarrassés de leurs espaces de bord. Le username doit
  déjà être correctement saisi : les espaces de bord et les transformations
  Unicode susceptibles de modifier l’identifiant sont refusés.
- Les limites et validateurs des champs du modèle utilisateur ainsi que les
  validateurs de mots de passe Django configurés sur le serveur s’appliquent.
- Les formules, cellules en erreur, nombres, dates et booléens sont refusés.

**Dans Excel, saisir les quatre colonnes au format Texte.** Un mot de passe
numérique saisi comme texte conserve ses zéros initiaux. Une cellule numérique
est rejetée : changer son format après saisie ne restaure pas les zéros ou la
précision déjà perdus. Ressaisir alors la valeur comme texte. Le mot de passe
textuel est utilisé tel quel, sans suppression des espaces, avec un plafond
de 1 024 caractères et refus d’une valeur entièrement vide/blanche.

## Validation, doublons et atomicité

Une erreur de ligne ou de format rejette **tout le fichier** avant création.
Les erreurs donnent un numéro de ligne et un motif générique, jamais le contenu
de la colonne mdp, même si un validateur ou une erreur SQL contient cette valeur.

Un username répété dans le classeur est une erreur bloquante. Un username déjà
présent en base est au contraire **ignoré**, sans changement du nom, du statut,
des habilitations ou du mot de passe existant. Les recherches en base utilisent
les comparaisons du backend ; la normalisation du modèle est contrôlée. Les
schémas Django SQLite/PostgreSQL actuels distinguent les usernames par casse.

La confirmation est liée à l’administrateur et à l’empreinte exacte des octets
du fichier par signature Django valable dix minutes. Un fichier modifié, un
autre administrateur ou un jeton expiré exige un nouvel aperçu. Le classeur
retransmis est intégralement revalidé, et les comptes existants sont recontrôlés
pendant la création.

Les créations et les entrées d’audit Admin sont atomiques. Une collision
concurrente sur l’unicité annule toutes les créations de la tentative. Rejouer
une confirmation déjà réussie ignore les comptes désormais présents ; aucun
compte n’est créé deux fois et aucun mot de passe n’est remplacé.

Une perte de connexion empêchant de confirmer le résultat du commit affiche
« Résultat non confirmé », plutôt que d’affirmer un succès ou un rejet certain.
Vérifier alors la liste des utilisateurs avant de recommencer.

## Garanties de confidentialité

Le handler habituel de l’application écrit les fichiers d’import sur disque.
Cette route le remplace **avant toute analyse du POST, y compris celle de CSRF**
par un handler exclusivement en mémoire et borné en taille. Il n’existe aucun
handler disque de repli pour ce parcours.

L’enveloppe technique est exemptée de l’analyse CSRF précoce afin de pouvoir
installer ce handler ; elle appelle ensuite une vue **obligatoirement protégée
par `csrf_protect`**. L’authentification et le droit de création sont contrôlés
avant lecture du fichier puis avant création. Les tests exercent de vrais POST
avec CSRF activé et vérifient qu’aucun fichier temporaire Django n’est créé.

Les mots de passe bruts restent en mémoire pendant la requête. Ils ne sont
stockés ni en session, ni en cache, ni dans une table ou un fichier intermédiaire.
Le jeton contient seulement l’empreinte du classeur et l’identifiant de l’acteur.
Les données de présentation sont une copie explicitement dépourvue de mdp.
Les fonctions manipulant les secrets sont marquées sensibles pour le mécanisme
de rapports d’erreur Django ; les erreurs affichées sont expurgées.

La seule persistance liée au mot de passe est le hash produit par `set_password()`
dans le compte final. L’audit réutilise `django.contrib.admin.models.LogEntry` :
acteur, identifiant du compte et message fixe de création, sans mot de passe.
Aucun e-mail ni partage d’identifiants n’est ajouté.

## Comptes sans accès projet : correction de sécurité

Chaque nouveau compte est actif, `is_staff=False`, `is_superuser=False`, sans
géographie, groupe, permission directe ou association `ProjectPortfolio`.
La propriété existante `is_global_admin` vaut donc False.

Les filtres existants des tableaux de bord, rapprochements, inventaires,
campagnes, exports et cadrage reposent déjà sur le portefeuille, avec une
exception explicite pour les administrateurs globaux existants.

**Faille identifiée et corrigée :** le POST « Mon portefeuille » permettait
auparavant à tout compte connecté de s’ajouter un projet connu dans l’inventaire.
Ce chemin pouvait contourner la politique « aucun portefeuille = aucun accès ».
Désormais, seuls les administrateurs globaux existants peuvent utiliser cet
ajout ; un POST direct classique reçoit 403, et le formulaire est masqué. Le
retrait de sa propre association reste possible, sans création d’accès.

Après attribution par l’import de portefeuilles existant, le compte voit seulement
ses projets et peut y effectuer les actions métier autorisées. Les autres projets
restent inaccessibles par URL directe. Les accès et exceptions des administrateurs
ne sont pas modifiés. Le mode maintenance actif bloque aussi cet import de comptes.

## Configuration et déploiement

Aucune dépendance supplémentaire : `openpyxl` est déjà déclaré. Aucune nouvelle
migration, table intermédiaire ou évolution du moteur/JSONL/cadrage.

Variables facultatives :

| Variable | Défaut | Effet |
| --- | --- | --- |
| `USER_IMPORT_MAX_BYTES` | `5242880` | Taille cumulée des fichiers d’une requête : 5 Mo |
| `USER_IMPORT_MAX_ROWS` | `500` | Maximum de lignes physiques de données examinées |

Le lecteur refuse aussi les archives de plus de 50 Mo décompressés ou 2 000
éléments. Les hash de mots de passe sont calculés dans la requête de confirmation :
pour de gros volumes, utiliser des lots adaptés au délai HTTP du déploiement.

Déployer le code et les templates puis redémarrer l’application. Aucune commande
de création de comptes n’est exécutée sur la base locale pendant le développement.

## Fichiers et tests

- `accounts/user_import.py` : lecture, validation, jeton et création atomique.
- `accounts/user_import_views.py` : réception RAM, formulaires et parcours.
- `accounts/admin.py`, `templates/admin/accounts/*`, `templates/admin/index.html` : boutons et écran Admin.
- `config/settings.py` : plafonds configurables.
- `projects/views.py`, `templates/projects/portfolio.html` : protection de l’ajout.
- `accounts/test_user_import.py`, `projects/tests.py`, `projects/test_portfolio_import.py` :
  recettes et mise à jour des scénarios d’ajout administratif.
- README application et guide des portefeuilles : liens et politique d’accès.

Commandes depuis `app-suivi-reconciliation` :

```powershell
python manage.py test accounts.test_user_import projects --noinput
python manage.py test --noinput
python manage.py makemigrations --check --dry-run
python manage.py check
```

La recette couvre le format réel synthétique, les hashes vérifiés par
`check_password`, les secrets absents de l’aperçu/bilan/session/audit, les
erreurs globales, les doublons et collisions, CSRF, les permissions existantes,
le bouton Admin, les limites, la signature de confirmation, le blocage en
maintenance et le parcours sans portefeuille → attribution → validation/correction.
Les essais PostgreSQL réels exigent une base de test dédiée et ne sont pas
remplacés par la simulation de collision ou les essais SQLite.

### Résultats locaux du 11 novembre 2026

- Suite complète Django : **402 tests recensés, 399 réussis et 3 ignorés**,
  en 182,231 s. Les trois cas ignorés exigent PostgreSQL (import et verrouillages
  concurrents) ; aucune base PostgreSQL dédiée n’a été utilisée.
- Recette ciblée initiale `accounts.test_user_import projects` : 26 tests
  réussis avant ajout des deux cas bouton Admin et maintenance.
- Après intégration du bouton sur l’accueil Admin : les **13 tests d’import**
  et le test de bandeau de maintenance, soit **14 tests réussis**, en 11,336 s.
- `makemigrations --check --dry-run` : aucune modification de schéma détectée.
- `manage.py check`, Ruff règles F sur les fichiers Python modifiés et
  `git diff --check` : réussis.
- Toutes les classes et fonctions des trois nouveaux fichiers Python possèdent
  une docstring française ; les méthodes existantes modifiées sont documentées.

Les vérifications utilisent exclusivement des comptes et classeurs synthétiques
sur une base de test. Aucun compte, portefeuille ou mot de passe de la base de
travail n’a été créé ou modifié, et le fichier réel n’a pas été chargé.
