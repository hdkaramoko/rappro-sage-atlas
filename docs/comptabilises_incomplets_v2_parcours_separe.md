# V2 : Comptabilisés incomplets, parcours séparé par projet

## Parcours et périmètre

Dans **Mes rapprochements → Contrôle des montants**, deux sous-vues sont
désormais accessibles, sans nouvel onglet principal :

- **Contrôles financiers** : groupes, pièces et écarts communs, avec leurs filtres.
- **Comptabilisés incomplets** : projets, puis seules lignes Atlas concernées,
  puis fiche V1 de recherche/correction/confirmation.

La file Envoyé SAGE reste inchangée. Le détail financier peut toujours présenter
les différents statuts nécessaires au calcul commun ; il ne sert plus de détail
du parcours de réparation des Comptabilisés incomplets. Pour les contrôles avec
un diagnostic source, le lien principal dirige vers le projet dédié ; le détail
financier reste accessible par un lien explicite.

Le filtre V1 `sage_missing` n'est plus proposé dans l'espace financier. Ses
anciens paramètres restent interprétés pour les URL existantes. Le tri financier
redevient projet/identifiant ; la priorité V1 ne constitue plus une seconde file
concurrente. Les champs et compteurs V1 restent conservés pour les diagnostics.

## Sélection SQL et résolution

`incomplete_views.incomplete_rows()` part du portefeuille autorisé, de la campagne
courante publiée, des lignes présentes et de `sage_missing_mask > 0`.
Le masque V1 est non nul uniquement pour une source Comptabilisé ; son calcul
déterministe et l'immuabilité des sources permettent d'éviter un nouveau scan
JSON du statut à chaque agrégation. Les Envoyé SAGE ne sont pas joints depuis
les contrôles, propositions ou allocations.

Le prédicat SQL de résolution reproduit `current_manual_link()` : lien actif,
version de correction identique, absence d'exclusion DUPLICATE active et égalité
avec la référence métier actuelle. Il utilise les relations uniques existantes
vers `ManualReconciliation` et `AtlasAdjustment`, sans sous-requête corrélée ni
jointure multiplicatrice aux allocations.

La référence prend la correction active, sinon la politique de montant source,
avec repli charges projet pour le montant Sage invalide/absent. Le bit du
diagnostic empêche de convertir un montant Sage invalide en faux zéro.
Le zéro valide reste une vraie référence zéro. Les montants importés sont les
scalaires canoniques V1 ; le cast SQL est décimal sur les deux bases.
Le montant JSON n'est évalué que pour un lien/version courant : les lignes sans
confirmation n'exigent pas cette extraction pour décider de leur résolution.

Une confirmation manuelle valable retire la source de **À traiter**. Annuler le
lien, changer sa correction ou invalider son montant la fait réapparaître. Le
masque et les informations Atlas d'origine ne sont jamais effacés. Le filtre
**Traitement** permet À traiter (défaut), Résolus ou Toutes dans les mêmes écrans.

Aucun indicateur de résolution supplémentaire, migration ou recalcul rétroactif
n'est nécessaire. Les écritures, réservations Sage et le cadrage utilisent les
services V1 sans changement de formules, tolérances, auto-validations ou sources.

## Comptage, filtres et navigation

La liste agrège en SQL par `project_code`, avec `Count(pk, distinct=True)` sur
les identifiants d'inventaire. Une source liée à plusieurs contrôles reste une
seule ligne. Tous les filtres de droits, projet, département, pôle, recherche et
traitement précèdent l'agrégation. Les libellés ne sont chargés que pour les
40 projets de la page ; un retrait concurrent de portefeuille est toléré sans
exposer de libellé devenu inaccessible.

Le détail projet ne charge que 25 sources, avec correction et lien préchargés.
Il présente identifiant, BAP, tiers/libellé, montant de référence avec sa
provenance, motifs et accès à la recherche V1. Aucun candidat Sage n'est calculé
pour toute la liste ; la recherche reste à la demande, dans la fiche existante.

La route dédiée vérifie le projet dans le portefeuille avant consultation et
interdit les POST. Les POST de correction/confirmation restent contrôlés par la
fiche et les services transactionnels V1. Les campagnes historiques conservent
leur lecture seule dans les parcours existants ; cette file vise la campagne
courante uniquement.

Le retour V1 garde page, filtres et lien vers la liste des projets. Une ancre de
ligne replace le tableau sur la ligne examinée ; si elle a quitté la file, une
ancre de repli permet de revenir au tableau sans remonter en tête de page.
Les projets entièrement résolus disparaissent de la file active, mais restent
consultables avec Résolus ou Toutes. La pagination conserve son comportement
habituel si une suppression de la file rend l'ancienne page hors limites.

## Vérifications et mesures

**475 tests : OK, dont 4 ignorés car un serveur PostgreSQL est requis**, dernière
exécution en 185,6 secondes. Les nouveaux tests couvrent notamment : groupe
mixte avec deux Envoyé, multi-affectation et déduplication, résolution/annulation,
invalidation de version et de montant, zéro, montant Sage invalide, filtres et
pagination, portefeuille/administrateur, POST forgé, campagne cachée, retour
contextualisé et ancre après résolution, absence d'écriture métier lors des GET.
Les montants, JSON et versions financiers restent identiques lors de la
consultation. Les tests V1 de réservations, tolérances, concurrence et audit sont
conservés. La compilation SQL PostgreSQL de l'agrégation complète est testée
sans connexion serveur ; aucune intégration PostgreSQL réelle n'est revendiquée.

Ruff sur les deux nouveaux modules Python, `makemigrations --check --dry-run`
et `git diff --check` passent.

Mesures locales sur données fictives : 10 001 sources incomplètes de 4 Ko,
51 projets, dont un projet à 5 001 lignes. Moyennes de trois lectures après
chauffe ; fonctions de vue directes, hors middleware HTTP, même schéma V1.
La V1 est chargée depuis le code HEAD précédent. Les contenus diffèrent
volontairement : la V1 affiche des contrôles mixtes, la V2 agrège des projets.

| Consultation | Temps indicatif | Requêtes |
| --- | ---: | ---: |
| Liste V1 des contrôles | 0,0358 s | 6 |
| Liste V2 des projets, 10 001 sources | 0,0514 s | 5 |
| Ancien détail mixte | 0,0340 s | 5 |
| Détail V2, projet à 5 001 sources, 25 affichées | 0,0281 s | 4 |
| Recherche V1 partagée, code métier inchangé | 0,0235 s | 14 |
| Liste active avec 10 000 projections de liens résolus fictifs | 0,1504 s | 5 |

Le dernier profil simule uniquement les relations de résolution pour mesurer la
lecture, sans confirmer des décisions financières réelles. Le coût SQL reste
proportionnel aux sources incomplètes sélectionnées, particulièrement quand les
liens actifs nécessitent la comparaison du montant. Ces mesures ne garantissent
pas un délai de production. Elles ne justifient ni migration lourde, ni nouvelle
matérialisation, ni infrastructure supplémentaire à ce stade.

La recette navigateur contrôle les trois vues à **390 et 1 440 px**, sans
débordement horizontal de page ; les tableaux défilent dans leur conteneur.
Les captures et mesures sont dans `.work_app/incomplete-v2-*`.

## Recette manuelle

Prérequis : la V1 et sa migration `0027` sont déjà appliquées. **Aucune nouvelle
migration, aucun réimport ni régénération du JSONL n'est requis pour cette V2.**

1. Ouvrir Mes rapprochements → Contrôle des montants → Comptabilisés incomplets.
2. Vérifier la ligne par projet et le nombre de sources à traiter, puis filtrer
   par projet/département/pôle selon le portefeuille.
3. Examiner le projet 19DDU0C041 : seules les sources Comptabilisé incomplètes
   doivent apparaître, même si leurs contrôles contiennent des Envoyé SAGE.
4. Ouvrir la ligne 1665867 et examiner le candidat Sage dans la fiche V1.
5. Appliquer si nécessaire la correction justifiée, refaire l'aperçu puis confirmer
   manuellement suivant les mêmes règles V1, sans augmenter la tolérance.
6. Revenir au projet : la ligne quitte la file active. Si elle était la dernière,
   le projet ne figure plus dans la liste des projets à traiter.
7. Choisir Résolus : la source, son diagnostic historique et sa décision restent
   consultables ; une révision ou annulation doit réintroduire la ligne active.
8. Vérifier le cadrage commun et refaire les accès avec un compte hors portefeuille.

## Fichiers

- `reconciliation/incomplete_views.py` : sélection SQL, agrégation et détail paginé.
- `review_views.py`, `urls.py`, `journey.py` : dispatch, route et retours autorisés.
- `global_views.py` : séparation du parcours financier et compatibilité des URL V1.
- Templates `incomplete_projects.html`, `incomplete_project.html`,
  `components/control_channels.html`, `global_controls.html`, `base.html` et CSS
  `workspace.css` : sous-vues, liens dédiés, présentation et navigation.
- `test_incomplete_v2.py`, adaptation du test V1 de navigation : recettes et
  conservation des garanties de l'ancien parcours financier.

Aucun service de décision, calcul de cadrage, import ou export n'est modifié.
Aucune opération sur la base réelle ni import du JSONL réel n'a été lancé.
