# Validation simplifiée et extraction JSON de la base

## Validation métier

Les cases « Je confirme cette affectation manuelle » et « Je confirme le risque
de multiple / de pièce partagée » ont été retirées. Le bouton **Valider** confirme
les valeurs, la sélection SAGE éventuelle et les risques calculés par le serveur.
Le choix des écritures candidates reste disponible : il définit l'affectation,
et ne constitue pas une confirmation supplémentaire.

Ce choix est présenté sous l'intitulé **Option retenue**, notamment pour départager
les correspondances ambiguës. Les numéros de ligne comptable et analytique restent
visibles ; l'identifiant technique reste utilisé en interne sans être affiché.

`LineReviewForm` ne reçoit plus les deux booléens. La vue transmet au service la
confirmation correspondant à l'action de l'utilisateur. Les contrôles de droits,
de versions et de cohérence ne changent pas. Les appels directs au service gardent
leurs paramètres explicites ; le changement concerne le parcours utilisateur.

Les commentaires restent obligatoires en cas de refus, d'affectation manuelle ou
de dérogation. Un diagnostic indéterminé bloquant ne devient pas validable par
le simple clic. Enregistrer un brouillon ou refuser ne crée aucune contribution
validée. `ReviewEvent` conserve les commentaires, écritures sélectionnées, risques
et dérogations ; les photographies de campagne restent alimentées.

## Export réservé au superutilisateur

Le lien **Exporter la base JSON** apparaît dans le menu latéral uniquement pour
les superutilisateurs. La vue contrôle aussi `is_superuser` et `is_active` côté
serveur : un compte `is_staff` seul reçoit HTTP 403, même avec l'URL directe.
L'accès anonyme impose la connexion. Seule la méthode GET est acceptée.

Le téléchargement inclut les tables métier des applications `accounts`, `projects`,
`reconciliation` et `imports_app` :

- comptes identifiant les auteurs, projets et portefeuilles ;
- sources Atlas, propositions SAGE et revues courantes ;
- campagnes, inventaires et photographies historiques ;
- événements successifs de validation, commentaires, corrections historiques ;
- contrôles de multiples, leurs arbitrages, événements et contributions ;
- journaux d'import et affectations des portefeuilles.

Les clés primaires et étrangères sont conservées, y compris pour les auteurs
devenus inactifs. Les campagnes non publiées sont présentes avec `published=false` :
elles doivent être distinguées des campagnes utilisables par le métier.

Les mots de passe (même hachés), sessions, tables internes de permissions Django,
compteur de révision d'import et fichiers externes ne sont pas exportés. C'est une
**extraction des données métier**, pas une sauvegarde restaurable avec `loaddata`.
La sauvegarde SQLite reste le mécanisme de restauration complète.

## Format et choix techniques

Le fichier `base-reconciliation-AAAAMMJJ-HHMMSS.json` contient :

```json
{
  "schema_version": 1,
  "exported_at": "2026-09-30T10:00:00Z",
  "tables": {
    "accounts.user": [{"id": 1, "username": "administrateur"}],
    "projects.projectportfolio": [{"id": 1, "user_id": 1, "project_id": 8}]
  }
}
```

Les exemples de lignes sont abrégés. Les dates sont en ISO, les décimaux en chaînes
pour préserver leur précision, et les champs JSON métier restent des objets/listes.
Chaque enregistrement est écrit sur une ligne distincte, dans le même document
JSON (ce n'est pas du JSONL). Cela évite une ligne unique de plusieurs centaines
de Mo, susceptible de provoquer `Invalid string length` dans VS Code. Un fichier
très volumineux peut néanmoins dépasser les capacités de l'éditeur.

`json_chunks()` utilise `iterator(chunk_size=500)` et `DjangoJSONEncoder` : les
tables ne sont pas chargées intégralement en mémoire. La lecture est transactionnelle
pour obtenir une photographie cohérente ; PostgreSQL utilise REPEATABLE READ.
SQLite utilise sa photographie de lecture, compatible avec le mode WAL du projet.

La vue prépare un fichier temporaire sur disque, puis ferme la transaction avant
de renvoyer un `FileResponse`. Un téléchargement lent ne conserve donc pas de
transaction sur la base. Le fichier est fermé/supprimé à la fin de la réponse,
et fermé immédiatement si la préparation échoue. Prévoir l'espace disque pour
l'extraction ; sur une grande base, sa préparation peut prendre du temps avant
le début du téléchargement. Aucun job de rapprochement n'est déclenché.

La réponse indique `private, no-store`. Le contrôle superutilisateur reste
indépendant du portefeuille : cet export porte volontairement sur toute la base.

## Vérifications

Les tests couvrent la validation HTTP sans cases avec risque et sélection manuelle,
le commentaire obligatoire et l'audit conservé ; l'interdiction d'export pour les
comptes ordinaires et staff ; la présence du lien pour le superutilisateur ; le
contenu JSON, les relations, les commentaires successifs et l'absence de secrets.
Aucune migration n'est nécessaire.
