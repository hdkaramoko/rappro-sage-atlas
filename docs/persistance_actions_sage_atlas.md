# Persistance des actions Sage / Atlas entre campagnes

Évolution du 6 novembre 2026 : les actions Lot 2 ne sont plus à refaire sur des
sources identiques. Aucun nouveau JSONL ni changement de configuration PostgreSQL
n'est nécessaire. Aucun changement de schéma : la migration 0020 reste suffisante.
La reprise intervient au prochain import d'une **nouvelle campagne**, après le
calcul initial, dans la transaction de publication existante.

## Identité et conditions de reprise

- Atlas : même `business_key` (identifiant source, projet, exercice), ligne présente
  et totalité des données Atlas normalisées identiques.
- Sage : chaque écriture sélectionnée doit avoir exactement le même contenu
  canonique : projet, exercice, pièce, date, journal, ligne comptable/analytique,
  tiers, libellés, devise, montant EUR exact et attributs source. La référence
  calculée et l'empreinte du fichier brut ne suffisent pas à identifier une écriture
  et ne font pas partie de cette comparaison. Le contenu doit être unique dans
  **les deux** inventaires. Aucun rapprochement approximatif ni fraction nouvelle.
- Même politique de montant, tolérance et exclusions Sage.
- Correction de doublon : au moins une autre ligne Atlas strictement identique
  hors identifiant, et exactement les mêmes témoins dans la nouvelle campagne.
  Une simple exclusion sans témoin ne se reporte pas automatiquement.
- Le lien doit déjà être confirmé sur la dernière version de correction.
- L'auteur d'origine doit encore être actif et autorisé sur le projet.
- La disponibilité des écritures et la capacité de toutes les pièces sont
  revérifiées par les services métier existants ; les collisions bloquent la reprise.

La campagne précédente est celle du même périmètre et exercice retenue par le
circuit d'import existant. Aucun report transversal de projet ou d'exercice.
Les actions annulées ne sont pas ressuscitées. Une correction seule ne valide
aucune correspondance, même si l'ancienne décision était AUTO.

## Résultat et confirmation

En cas de succès, de nouveaux objets correction/lien/allocations sont créés dans
la nouvelle campagne. Les contrôles courants sont recalculés sur les seules clés
concernées ; le diagnostic initial et toute la campagne précédente restent intacts.
La correction et le lien d'une même ligne sont repris dans un savepoint atomique :
un échec du lien ne laisse pas une correction partiellement reprise.
Les corrections sans lien sont traitées en premier pour rendre disponibles leurs
capacités comptables. Une reprise incompatible reste à confirmer, sans déroger au
contrôle de capacité.

Un événement `CARRY` indique explicitement l'origine et le caractère automatique ;
les objets repris conservent l'auteur et le commentaire de l'action initiale.
La page de ligne affiche la reprise avec un lien vers l'origine. Une correspondance
reprise reste d'origine **MANUAL**, jamais une nouvelle preuve ou règle moteur AUTO.

En cas de modification, ambiguïté, absence d'écriture ou incompatibilité de droits,
un événement `CARRY_PENDING` conserve la proposition et ses motifs. La page affiche
le montant/motif précédent et les pièces antérieurement sélectionnées. Le formulaire
de correction est prérempli ; l'utilisateur doit l'enregistrer explicitement et
vérifier/sélectionner les écritures actuelles dans la recherche pour confirmer un
rapprochement. Les mêmes contrôles de droits, version et capacité s'appliquent.
Une proposition non traitée reste visible à la campagne suivante ; elle n'est pas
automatiquement appliquée au seul motif qu'un import supplémentaire a eu lieu.
Une ligne Atlas absente n'est pas modifiée ; son historique reste consultable.

## Import et audit

`business_carry.py` prépare les comparaisons des seules lignes ayant une action ou
une proposition, indexe les contenus Sage des projets concernés et appelle les
services transactionnels existants. La reprise ajoute une lecture des inventaires
pendant l'import, jamais pendant la simple consultation d'une ligne.

`campaigns.import_campaign` appelle la reprise après `initialize_controls`.
Le staging SQLite copie désormais les quatre tables métier Lot 2 dans la publication
atomique, avant les projections qui les référencent. Les triggers de révision
existants empêchent toujours une publication issue d'une préparation périmée.
PostgreSQL conserve le circuit ORM et ses verrous ; aucun choix de base modifié.

## Recette

Les tests de `reconciliation.test_business` couvrent la reprise du lien inchangé,
une correction seule sur trois campagnes, la sélection de plusieurs écritures avec
corrections, le changement Atlas, le changement Sage, les contenus ambigus,
l'absence de témoin de doublon, la suppression des droits, les annulations,
l'idempotence et la consultation des propositions sans mutation.
Le scénario `imports_app.test_sqlite_staging` vérifie la reprise réelle des corrections
et des liens sur une base sur disque, ainsi que le refus d'une publication périmée.
Les tests de concurrence PostgreSQL nécessitent une base PostgreSQL dédiée.

Vérifications exécutées le 6 novembre 2026 :

- Suite Django complète : **257 tests, succès, 3 ignorés** (concurrence PostgreSQL).
- Suite moteur : **192 réussis, 1 ignoré** (recette réelle optionnelle).
- Scénario SQLite sur disque : succès, reprise effective des quatre tables métier
  et refus de publication après modification concurrente.
- `makemigrations --check --dry-run` : aucune migration manquante.
- `git diff --check` : aucune erreur d'espacement.
- [Inventaire AST des docstrings](persistance_docstrings_inventory.md) :
  **22 définitions nouvelles/modifiées**, aucune docstring absente.

Aucun déploiement, migration applicative, commit, push ou accès à la base de
production n'a été effectué pour cette évolution.
