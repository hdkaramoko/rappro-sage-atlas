# Contrôle collectif des sommes signées

Évolution du 8 novembre 2026.

Le contrôle des montants compare désormais les sommes signées Atlas et Sage
par clé de groupe. Un écart absolu inférieur ou égal à 0,01 € est équilibré.
Les signes mixtes et le nombre de lignes/écritures ODS/ODG ne constituent plus
des anomalies. Un groupe équilibré atteste l'égalité des totaux ; une erreur
positive peut néanmoins compenser une erreur négative dans le même groupe.

Le contrôle conserve ses garde-fous : identités absentes ou répétées, clés
incomplètes, montants absents, sources hors groupe, exclusions, affectations
ambiguës et preuves périmées. Les règles de validation individuelle et le
snapshot signé partagé avec ces parcours restent inchangés. Les motifs hérités
du snapshot concernant les signes sont filtrés uniquement dans le diagnostic
collectif ; ses écarts sont calculés sur les sommes signées, jamais sur les
valeurs absolues des totaux.

Exemple réel vérifié dans `campagne_08112026.jsonl` : projet `16DDU0C206`,
tiers `M05297`, libellé `odp juin 2026`. Les trois lignes Atlas totalisent
8 516,27 €, comme les quatorze écritures Sage, dont une écriture de −95,21 €.
Ce groupe devient équilibré. Les trois pièces sont également équilibrées
séparément, mais cette vérification supplémentaire n'est pas exigée par la
règle collective par groupe.

## Campagnes existantes

La migration de données `0023_group_signed_amounts` retire uniquement les trois
anciens motifs des diagnostics courants indéterminés de la campagne active
publiée. Elle dérive les états des écarts signés déjà stockés, conserve tous les
montants et autres motifs, recalcule la signature et avance la version courante.
Le diagnostic initial, les campagnes historiques, les décisions, les sources,
les affectations, les indicateurs d'attente et le drapeau historique
`auto_validated` restent intacts. Le traitement est idempotent et paginé par
clé primaire, par lots de 250, sous verrou de campagne.

Au déploiement, exécuter `python manage.py migrate`. Il n'est pas nécessaire de
régénérer le JSONL ni de réimporter la campagne. Cette migration n'a pas été
exécutée sur la base utilisateur pendant le développement.

Les nouveaux imports et recalculs utilisent directement la nouvelle règle.
Le drapeau `auto_validated` des nouveaux diagnostics collectifs suit l'état
équilibré ; ce drapeau ne déclenche aucune validation individuelle de ligne.

## Vérification

Tests des groupes ODS à plusieurs écritures, signes mixtes, tolérance au
centime, totaux opposés, montants absents et doublons techniques. La recette
de migration vérifie plus de 250 résultats, la conservation de l'historique,
les exclusions, les motifs restants, la signature et l'idempotence.

Résultats : 227 tests moteur réussis lors de la suite complète, puis les cinq
tests ciblés réussis après correction d'une assertion de format décimal.
La suite Django a exécuté 261 tests (2 ignorés) ; le seul test qui attendait
encore le veto de cardinalité a été adapté à la nouvelle règle et rejoué avec
succès. Aucun changement de modèle détecté par `makemigrations --check`.
L'[inventaire des docstrings](controle_groupes_sommes_signees_docstrings.md)
recense les définitions nouvelles ou modifiées.
