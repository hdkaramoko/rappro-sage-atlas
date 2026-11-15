# Comptabilisé incomplets : diagnostic et association Sage manuelle

## Points d'entrée et choix d'architecture

L'audit confirme le parcours existant : `global_views.control_workspace` et
`global_control_detail` pour le contrôle des montants ; `business_views.inventory_detail`
pour la recherche/correction ; `business.search_sage`, `selection_summary`,
`correct_inventory`, `confirm_inventory_link`, `cancel_inventory_link` et
`recalculate` pour les opérations transactionnelles du Lot 2.

Le lot étend ces services, sans second registre de décisions ni nouveau moteur.
Les réservations `ManualAllocation`, les événements `CampaignAction`, les UUID
idempotents, les versions optimistes et le verrou campagne sont conservés.
Une ligne Comptabilisé peut n'avoir aucune `LineReview` : la décision et son
audit restent alors portés par `ManualReconciliation` et `CampaignAction`.

## Diagnostic et index de consultation

`incomplete_accounting.missing_mask` vérifie les seules sources `Comptabilisé` :

| Bit | Défaut |
| --- | --- |
| 1 | Charges Sage Atlas absentes, non numériques, non finies ou hors domaine monétaire existant |
| 2 | Pièce Sage absente ou vide après suppression des espaces externes |
| 4 | Date comptable absente, invalide ou hors exercice |

Zéro est présent et valide. Les charges projet ne remplacent jamais le montant
source Sage absent. Le statut source reste Comptabilisé.

La migration `0027_incomplete_accounting_diagnostics` ajoute deux projections :
`CampaignInventory.sage_missing_mask` et
`CampaignGlobalControl.sage_incomplete_count`, plus leurs index. Elle parcourt
une fois, par lots, les seules lignes Comptabilisé présentes de la campagne
publiée courante ; elle ne rejoue ni matching, ni décisions, ni calcul comptable.
Les sources JSON, montants et résultats financiers ne sont pas réécrits.
Les historiques ne font pas l'objet d'un rattrapage global.

Les prochains imports remplissent le masque avec les lots d'inventaire. Les
compteurs sont calculés par lots lors de la préparation des contrôles, puis
maintenus sur les seules clés recalculées ou reconstruites. Le staging SQLite
transfère déjà ces deux tables et reprend automatiquement leurs nouvelles colonnes.
Les triggers de révision SQLite sont restaurés après ajout/retrait des colonnes,
dans les deux sens de migration, pour conserver l'anti-concurrence des imports.

La liste trie par compteur décroissant, puis projet/identifiant. Le filtre
« Informations Sage manquantes », Toutes par défaut, s'ajoute aux filtres existants.
Les filtres d'état et de portefeuille gardent leur sens. Les défauts source
restent visibles après une association manuelle : la photographie n'est jamais
complétée silencieusement. Ce diagnostic ne signifie pas « aucune écriture Sage ».

## Recherche, référence et confirmation

La recherche reste limitée aux écritures éligibles et identifiables du même
projet, exercice et campagne, dans le portefeuille autorisé. Aucun candidat
n'est calculé pour toute la liste : la recherche est déclenchée sur la fiche.
Les pages de résultats restent limitées à 25 écritures.

Pour les incomplets, le classement SQL privilégie BAP, tiers et libellé
concordants, puis pièce/date et montant/signe. Il utilise les normalisations
simples déjà admises (espaces externes, comparaison sans casse), sans nouveau
rapprochement flou ni nouvelle tolérance. Le BAP seul ne vaut pas validation.
L'identité technique, la pièce, la date, le BAP, les tiers/libellés, les indices
et la disponibilité sont affichés. L'utilisateur peut toujours rechercher une
autre écriture dans le périmètre ; l'égalité de montant n'est pas imposée par défaut.
Un filtre de montant explicitement saisi garde son comportement d'égalité.

La référence de revue est la correction active, sinon le montant source connu.
Pour un Comptabilisé dont ce montant est absent, les charges projet sont une
référence de comparaison distincte. L'aperçu expose le retenu, cette référence,
la somme Sage sélectionnée et leur écart exact, avec signe.

Le cas 1665867 / GNF0126041594 présente ainsi **4 213,50 − 4 213,38 = +0,12 €**.
La confirmation brute est refusée puisque l'écart dépasse la tolérance existante
de 0,01 € de la campagne de recette. Une correction AMOUNT justifiée doit être
enregistrée séparément, suivie d'un nouvel aperçu et d'une confirmation avec un
autre commentaire. Une correction ne crée aucune validation automatique.
Si l'écart est admissible selon les règles existantes, une confirmation humaine
peut utiliser cette référence, sans inventer un montant source.

Les services revérifient sous verrou : droits, campagne ouverte, versions,
unicité des références, éligibilité, réservations/contributions antérieures,
sélection entière et capacité de toutes les pièces. Le signe de référence de
la source reste protégé même après une exclusion provisoire comme doublon.

## Recalcul et annulation

Le lien courant fournit son montant métier au retenu et projette les informations
Sage sélectionnées dans les seules données dérivées du calcul. Le statut et les
champs JSON Atlas ne sont pas modifiés. Les anciennes et nouvelles clés sont
recalculées, puis le seul projet concerné est actualisé.

Le montant Sage est toujours compté depuis son inventaire exhaustif, une seule
fois. Le montant Atlas est projeté une seule fois sur les écritures affectées.
L'initial absent reste inconnu, même quand le retenu devient calculable. Un lien
manuel courant peut lever ce blocage précis ; il ne retire pas les autres causes
d'insuffisance ni les écarts résiduels. Les règles générales de cadrage, ODS/ODG,
ODA, exclusions et tolérances ne sont pas refondues.

Une annulation libère les réservations, conserve l'audit et rétablit l'état
calculé depuis les sources/corrections restantes. Modifier une correction
invalide la confirmation antérieure et exige une nouvelle confirmation.

## Performances et recette exécutée

Comparaison locale du backend original de HEAD et du backend modifié, sur les
mêmes données fictives (1 002 contrôles), moyenne de trois lectures après chauffe.
Les deux versions utilisent le même schéma migré pour isoler le coût des vues :

| Consultation directe, hors middleware HTTP | Avant | Après | Requêtes avant / après |
| --- | ---: | ---: | ---: |
| Liste | 0,0239 s | 0,0244 s | 6 / 6 |
| Détail | 0,0112 s | 0,0113 s | 5 / 5 |

Ce sont des mesures indicatives, sans garantie de temps en production. La priorité
et le filtre lisent des colonnes indexées ; aucun scan global des JSON ni calcul
de tous les candidats n'est ajouté à la consultation. L'initialisation des
diagnostics reste un coût ponctuel de migration/import.

La recette navigateur vérifie liste, détail, recherche et aperçu à **390 et
1 440 px**, sans débordement de page. Les tableaux gardent leur défilement
horizontal. Les captures et mesures restent dans `.work_app/incomplete-*`.

Tests ajoutés : diagnostic et zéro, écart 0,12 €, correction/confirmation,
égalité manuelle, annulation, idempotence, source préservée, autre blocage
persistant, corrections successives, signe, portefeuille, campagne/exercice,
écritures exclues/réservées, multi-sélection, classement, pagination, priorité,
consultation sans écriture métier, migration courante et triggers SQLite.
Un test PostgreSQL à deux connexions couvre la compétition entre deux sources
incomplètes ; il est ignoré sur SQLite, sans prétendre l'avoir exécuté sur serveur.

Dernière exécution complète : **463 tests, OK (4 ignorés car PostgreSQL requis)**,
en 177,6 secondes. Les nouvelles recettes ciblées et le test de coût avec 2 000
écritures Sage supplémentaires passent sans relever les seuils existants.
Ruff sur les cinq nouveaux modules de diagnostic/tests, `makemigrations --check
--dry-run` et `git diff --check` passent. Aucun import du JSONL réel ni migration
sur la base applicative existante n'a été exécuté.

## Installation et recette manuelle

**Migration nécessaire ; aucun réimport ni nouvelle génération du JSONL requis.**
La migration sur la base réelle n'est pas exécutée dans cette intervention.

1. Appliquer le code et la migration `0027`. Sur SQLite, utiliser la préparation
   sauvegardée existante : `.venv/Scripts/python.exe manage.py prepare_sqlite_imports --migrate`.
   Sur PostgreSQL : `python manage.py migrate`, suivant le déploiement habituel.
2. Ouvrir Mes rapprochements → Contrôle des montants avec un compte autorisé sur
   le projet 19DDU0C041. Choisir Informations Sage manquantes = Oui.
3. Ouvrir le contrôle prioritaire puis la ligne 1665867. Vérifier les trois champs
   source manquants et le statut source Comptabilisé.
4. Choisir « Rechercher une correspondance Sage ». Vérifier GNF0126041594,
   le 07/04/2026, BAPETR260400447, CABINET_KPC et le libellé correspondant.
5. Sélectionner l'écriture à 4 213,38 € et ouvrir l'aperçu. Vérifier la référence
   4 213,50 €, l'écart +0,12 € et le refus d'une confirmation brute hors tolérance.
6. Ouvrir Corriger, enregistrer 4 213,38 € avec une justification distincte.
   Vérifier qu'aucune association n'a été confirmée par cette seule correction.
7. Refaire l'aperçu, puis confirmer avec commentaire. Vérifier l'acteur, l'audit,
   les références réservées, le retenu et le recalcul ciblé du projet.
8. Vérifier que les champs sources sont toujours vides, que Sage n'est pas doublé,
   et que les autres écarts/causes bloquantes du projet restent visibles.
9. Réviser ou annuler l'association ; vérifier la libération de l'écriture,
   l'événement d'audit et le nouveau cadrage.
10. Refaire les consultations avec un compte sans portefeuille : aucun accès aux
    détails ni action par URL directe ne doit être possible.

## Fichiers concernés

- `incomplete_accounting.py`, `incomplete_candidates.py` : diagnostic, référence,
  fraîcheur du lien et classement explicable.
- `models.py`, migration `0027`, `campaigns.py`, `global_control.py` et
  `accounting_scope.py` : matérialisation et maintenance des index techniques.
- `global_views.py`, `business_views.py`, templates liste/détail/fiches et CSS :
  priorité, filtre, diagnostic, recherche et aperçu dans les écrans existants.
- `business.py`, `business_calculation.py`, `accounting.py` : extension ciblée du
  parcours manuel et du calcul dérivé, sans écrasement des sources.
- `test_incomplete_accounting.py`, `test_incomplete_migration.py`,
  `test_incomplete_concurrency.py` : nouvelles recettes automatiques.
