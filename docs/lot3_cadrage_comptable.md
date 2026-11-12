# Lot 3 : cadrage comptable autonome

**Évolution du 12 novembre 2026 :** le [cadrage exhaustif et le diagnostic ODA](cadrage_exhaustif_oda.md)
incluent désormais tous les Sage éligibles du projet, même sans Atlas. Les motifs
individuels sont distingués des vrais blocages de calcul. Les formules ci-dessous
sont actualisées ; les résultats de recette historiques restent ceux du Lot 3 initial.

## Note de conception avant implémentation — 9 novembre 2026

Les contrôles globaux matérialisés fournissent les contributions Comptabilisé
actuellement retenues et les allocations Envoyé SAGE validées et fraîches.
Le cadrage les consulte sans rejouer le moteur. Le Sage d'un groupe entre dans
le périmètre lorsqu'il existe une contribution Atlas comptabilisée ou confirmée,
pas lorsqu'une proposition est seulement disponible. Les écritures sont déduites
de l'inventaire Sage signé, une fois par référence technique. Les types exclus
par la politique de campagne et les groupes Sage sans Atlas restent hors total.

Les montants initiaux suivent `source_amount` : Comptabilisé utilise la politique
comptable de campagne (normalement Total charges SAGE), les Envoyé SAGE suivent
la valeur source déjà définie par l'application. Les corrections et montants
confirmés suivent les projections existantes ; aucune nouvelle validation.

Les clés ODS/ODG restent composites. Une clé incomplète, une collision de référence,
un montant manquant ou une projection non déterministe rend le périmètre concerné
insuffisant. Les signes mixtes et la cardinalité ne sont pas de nouveaux obstacles.
Un Atlas sans Sage identifié reste visible ; son comparateur est nul uniquement
si l'inventaire complet permet effectivement de constater l'absence d'écriture.

Deux tables techniques sont nécessaires pour servir la liste filtrée et les
groupes paginés sans calculer toute la campagne dans une requête web. La première
stocke les synthèses projet et leurs postes par type ; la seconde les résultats
par contrôle existant. Une préparation explicite des campagnes déjà importées
lit leurs résultats, sans recalcul ni modification de leurs décisions. Les
nouveaux imports préparent la synthèse ; les actions actualisent les projets
touchés dans leur transaction. Les campagnes sans inventaire Sage complet
affichent Données insuffisantes.

## Architecture livrée et formules

Le menu principal **Cadrage comptable** ouvre `/rapprochements/cadrage/`.
La liste affiche une ligne par projet, avec Atlas initial, Atlas retenu,
Sage retenu, écart signé et état. Les ventilations et ajustements restent dans
le détail pour limiter la largeur. Les filtres multisélection proposent Toutes
en premier ; recherche par code/nom, campagne publiée, tri Non cadré en premier
et pagination de 40 projets. Chaque vue filtre les projets par le portefeuille
existant. Le détail `/rapprochements/cadrage/projet/<id>/` propose les cartes,
les types, puis 25 groupes paginés. Les retours conservent les URL locales et
les filtres. Les corrections restent dans les fiches métier existantes.

`AccountingProject` conserve la synthèse et les postes par type.
`AccountingGroup` référence un `CampaignGlobalControl` unique : aucune copie
de décision et aucune nouvelle validation. Ces deux modèles sont des projections
reconstructibles créées par la migration **0024_accounting_rollups**.

- **Atlas initial** = charges sources Comptabilisé + charges sources Envoyé
  SAGE ; les autres statuts ne contribuent pas. Le champ source est celui de
  `business.source_amount`, sans substitution par un montant projet générique.
- **Envoyé confirmé** = somme des allocations effectivement retenues dans
  `confirmed_allocations` des contrôles courants. Une ligne peut se répartir
  sur plusieurs groupes, mais ses contributions sont déjà vérifiées par le
  service métier ; son montant initial n'est compté qu'une fois.
- **Atlas retenu** = Comptabilisé corrigé et non doublon + Envoyé confirmé,
  moins les contributions dont tout le comparateur Sage est exclu par type.
- **Sage retenu** = somme de toutes les écritures éligibles du projet/exercice,
  avec ou sans contribution Atlas, selon les exclusions enregistrées dans la
  campagne. Les doublons techniques prouvés sont neutralisés et tracés. Aucune
  jointure au montant ne décide du périmètre.
- **Ajustements** = Comptabilisé retenu avant exclusions de types + Envoyé
  confirmé − Comptabilisé initial − initial des Envoyé actuellement confirmés.
- **Écart** = Atlas retenu − Sage retenu, arrondi par `Decimal.quantize(0.01)`
  selon la convention existante. Seul **0,00 €** donne Cadré. Un écart de
  0,01 € reste Non cadré ; ce n'est pas la tolérance des anciens contrôles.

L'équation explicative est : Atlas initial − Envoyé initial non confirmé +
ajustements − Atlas hors types = Atlas retenu. Les postes par type se somment
aux totaux projet avant arrondi d'affichage. Des écarts locaux peuvent se
compenser sans retirer Cadré au projet.

Les types sont les préfixes de trois caractères des pièces Sage du groupe.
Une clé ODS/ODG couvrant plusieurs préfixes reste **MIXTE**, sans fractionner
artificiellement l'Atlas. Sans preuve Sage, le type standard provient de la
pièce Atlas ; une clé composite reste affichée ODS/ODG. **Non attribué / Non
confirmé** porte les Envoyé sans confirmation. Un retenu comptabilisé retiré par
un lien périmé est conservé dans son propre groupe source avec diagnostic. Les chiffres
initiaux des Comptabilisé suivent leur pièce source, les retenus suivent leur
groupe actuel : un changement de type entre ces colonnes peut donc être légitime.

Les écritures Sage hors rattachement et les types exclus sont comptés dans
deux postes séparés et disjoints. Une exclusion Sage complète expose aussi
l'Atlas correspondant hors périmètre : il ne disparaît pas silencieusement.
La part Atlas d'un type explicitement exclu est également retirée d'un groupe
ODS/ODG mixte lorsque sa pièce source la détermine. Un doublon Atlas exclu ne suffit pas à rattacher Sage si
aucune autre contribution Atlas ne subsiste ; ses montants initiaux et son
ajustement restent visibles.

Les clés ou références individuelles ambiguës restent des diagnostics. Seuls les
montants indispensables absents et les véritables impossibilités de déterminer
le périmètre produisent **Données insuffisantes**.
Les totaux non calculables restent absents, jamais remplacés par 0 €. Les postes
disponibles restent consultatifs. Une anomalie de signes ou de cardinalité seule
ne bloque pas le cadrage. Le diagnostic existant et l'état du nouveau cadrage
restent distincts, sans modifier les règles de l'un ou de l'autre.

## Préparation, actualisation et déploiement

Depuis `app-suivi-reconciliation`, après déploiement du code :

```powershell
python manage.py migrate
python manage.py prepare_accounting
```

La deuxième commande prépare uniquement la campagne publiée courante et affiche
le nombre de projets et sa durée. Pour rendre consultable une photographie
historique précise : `python manage.py prepare_accounting --campaign ID`.
Cela lit ses inventaires/décisions figés, sans recalculer le moteur, les anciens
contrôles ou les décisions. Sans préparation, l'écran indique explicitement
l'absence de synthèse disponible ; aucun résultat nul n'est fabriqué.

Les imports futurs préparent leurs agrégats en fin d'import, après les reprises.
Les corrections, confirmations, refus et annulations réutilisent le recalcul
Lot 2 puis reconstruisent uniquement les projets touchés déjà préparés, dans
la même transaction. L'affichage web ne lance jamais de préparation. Le verrou
Campaign utilisé par les services garantit une photographie cohérente pendant
la préparation explicite. Chaque projet est préparé atomiquement.

Aucune migration ni préparation n'a été appliquée à la base utilisateur pendant
le développement. Aucun nouveau JSONL n'est requis. Aucun changement de signe,
d'auto-validation, d'affectation ou de persistance intercampagnes.

## Performance et limites mesurées

Recette SQLite reproductible :

```powershell
python manage.py test reconciliation.test_accounting --noinput --verbosity 0
```

Sur les données synthétiques :

| Opération | Volume | Durée observée | Requêtes |
|---|---|---:|---:|
| Liste paginée | 120 projets, 12 000 groupes | 0,018 à 0,052 s | 11 |
| Préparation d'un projet | 1 000 groupes + écritures supplémentaires | 0,09 à 0,13 s | 34 |

La préparation lit au maximum 100 contrôles par lot et leurs écritures en flux,
sans charger tous les groupes de la campagne en mémoire. La liste lit seulement
les synthèses projet ; le détail charge la seule page de groupes. Les numéros
de références en collision sont recherchés en SQL. Une action sur un très gros
projet reconstruit sa synthèse entière : ce coût reste proportionnel au projet
et doit être évalué sur la base complète. Ces temps synthétiques ne prédisent
pas le coût de préparation de la campagne complète ni les latences PostgreSQL.
Les compteurs globaux portent sur les projets autorisés et filtrés.

Les requêtes et modèles utilisent l'ORM commun SQLite/PostgreSQL, sans fonction
SQL spécifique à PostgreSQL. Aucun serveur PostgreSQL de recette ni navigateur
pilotable n'est disponible dans cette session ; les tests visuels responsive et
le benchmark sur PostgreSQL restent à exécuter dans l'environnement de déploiement.

## Résultats des tests

`python manage.py test --noinput --verbosity 0` : **323 tests exécutés,
320 réussis et 3 ignorés**, en 122 secondes. Les 13 tests spécifiques couvrent
le périmètre Sage, l'absence de double comptage, les Envoyé non confirmés,
les corrections et doublons, validation/refus/annulation, exclusions de type,
compensations locales, clés ODS incomplètes, collisions, données absentes,
consultation historique, permissions et performances. Les autres tests couvrent
également les imports, contrôles, filtres et actions déjà existants.

`makemigrations --check --dry-run` ne détecte aucun changement de modèle manquant.
`git diff --check` ne signale aucune erreur. Les
[43 définitions nouvelles ou modifiées](lot3_cadrage_docstrings.md) disposent
toutes d'une docstring française. Les tests de migrations antérieurs restaurent
désormais le dernier schéma pour ne pas laisser les tables de cadrage absentes
dans les recettes suivantes.

## Fichiers principaux

- `reconciliation/accounting.py`, `accounting_models.py`, `accounting_views.py` : agrégats et consultation.
- `reconciliation/management/commands/prepare_accounting.py` et migration `0024_accounting_rollups.py`.
- `reconciliation/business.py`, `campaigns.py` : préparation et actualisation ciblée.
- `reconciliation/models.py`, `urls.py`, `journey.py`, `templatetags/review_ui.py` : enregistrement, liens et formats.
- `templates/base.html`, `templates/reconciliation/accounting_list.html`, `accounting_detail.html`, `static/css/workspace.css`.
- `reconciliation/test_accounting.py` et restauration du schéma courant dans les trois recettes de migrations antérieures.

## Recette utilisateur

1. Préparer la campagne, ouvrir le menu autonome et vérifier filtres, Toutes,
   pagination, recherche et retour depuis un projet.
2. Ouvrir un type, son groupe et son contrôle, puis la ligne Atlas ; revenir
   jusqu'au tableau projet en conservant le contexte.
3. Confirmer un Envoyé Sage : son montant sort du poste non confirmé et entre
   une seule fois dans l'Atlas retenu. Annuler ou refuser et vérifier l'inverse.
4. Corriger un Comptabilisé : vérifier montant initial intact, ajustement,
   montant retenu et état courant. Tester également l'exclusion d'un doublon.
5. Vérifier un groupe Sage sans Atlas : il est inclus dans Sage retenu et son
   écart est visible. Un type explicitement exclu reste hors périmètre. Vérifier aussi un projet à
   données insuffisantes, une ancienne campagne et les accès hors portefeuille.
6. Vérifier les largeurs ordinateur/fenêtre étroite, le clavier et les textes longs.
