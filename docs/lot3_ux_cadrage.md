# Lot 3 : UX du cadrage comptable

## Campagne implicite

La liste sélectionne la campagne publiée la plus récente (`created_at`, puis
identifiant), **accessible et prête dans le portefeuille de l'utilisateur**.
Une synthèse préparée porte le marqueur existant `data.prepared=true` ; un état
`INSUFFISANT` n'est pas une préparation en cours : la synthèse existe mais ses
données ne permettent pas le cadrage.

Pour ne pas afficher une préparation partielle, des requêtes EXISTS vérifient
que les projets Atlas présents et Sage autorisés ont chacun une synthèse préparée.
Seuls des codes et indicateurs sont lus, jamais les inventaires en mémoire. La
disponibilité concerne le portefeuille : une préparation manquante sur un projet
interdit ne bloque pas les projets autorisés. Sans campagne prête, les messages
distinguent absence de publication, cadrage non préparé et absence d'accès.

Le sélecteur est retiré. Nom, exercice et date de création/import de campagne
restent visibles. Un ancien paramètre `campaign` est ignoré avec une indication
explicite ; il ne permet pas de consulter une campagne interdite ou non préparée.
Les URL de détail historiques et leurs permissions restent inchangées.

## Deux filtres exclusifs et indépendants

Les formulaires GET natifs proposent Toutes (défaut), Avec écart, Équilibrées.
Les paramètres sont `type_state` et `group_state` ; une valeur inconnue revient
à Toutes. La sélection de type existante, `type`, continue de limiter les groupes.

- **Types** : le filtre compare à zéro l'écart déjà enregistré, sans nouvel
  arrondi. Pour qualifier un type d'équilibré ou avec écart, ses totaux doivent
  être présents et ses groupes comparés ne doivent pas être insuffisants.
  Les postes non confirmés, sans comparaison ou hors périmètre seuls restent
  dans Toutes, même si leur écart retenu est numériquement nul.
- **Groupes** : les états stockés CADRE/NON_CADRE, les totaux et l'écart stockés
  déterminent le filtre, sur les seuls groupes effectivement dans le périmètre.
  Les groupes insuffisants/hors périmètre restent dans Toutes. Le filtrage et
  la pagination à 25 lignes restent en SQL.

Les types sont les quelques postes du JSON de synthèse du seul projet ; ils ne
sont pas recalculés. Une agrégation SQL des statuts par type empêche de qualifier
abusivement un poste contenant des groupes insuffisants. Aucun groupe complet
n'est chargé en mémoire pour filtrer.

Les compteurs et messages vides suivent chaque filtre. Le formulaire des types
préserve la page et le filtre des groupes. Celui des groupes remet seulement
`page=1`, en conservant le type et l'autre filtre. Voir les pièces transmet le
type et revient à la première page de ses groupes.

## Navigation et présentation

Les liens de pagination ajoutent `#accounting-groups` pour première/précédente/
numéro/suivante/dernière page. Le composant partagé accepte une ancre optionnelle ;
les autres écrans ne la reçoivent pas et conservent leurs liens. Un retour depuis
le contrôle conserve également cette ancre, les filtres et le numéro de page.
Les changements de filtre ciblent leur bloc respectif via un fragment HTML,
sans AJAX, JavaScript ni dépendance supplémentaire.

La [présentation compacte v2](lot3_ux_cadrage_v2.md) place Atlas initial et Sage
retenu sur la première rangée, puis Atlas retenu et l'écart global sur la seconde.
Comptabilisé et Envoyé SAGE initial restent sous Atlas initial.
L'écart global et l'état sont regroupés ; les confirmations, ajustements et
montants hors comparaison restent secondaires. L'accordéon de périmètre est
conservé. Les colonnes se replient sur fenêtre étroite, sans troncature des
montants ; les tableaux gardent leur défilement local.

## Périmètre et vérification

**Aucun changement des règles de cadrage ni tolérance ±1 €.** Aucun calcul
financier, état, agrégat, modèle, migration, moteur, JSONL, signe, décision,
correction ou mécanisme intercampagnes n'est modifié. Les GET ne préparent pas
les synthèses et ne déclenchent aucune maintenance.

Tests ciblés :

```powershell
python manage.py test reconciliation.test_accounting_ux reconciliation.test_accounting --noinput --verbosity 0
```

Les 20 tests passent : sélection/publiée/prête/partielle/interdite, messages,
ancien paramètre, filtres indépendants, ancre sur toutes les pages, remise à 1,
retour depuis le contrôle, conservation exacte des snapshots après confirmation
et correction, valeurs négatives stockées et groupes ODS/ODG. Sur la recette
120 projets/12 000 groupes, la liste a pris 0,028 s pour 14 requêtes, dont les
nouveaux tests EXISTS de disponibilité ; aucun inventaire n'est chargé.

Suite complète : `python manage.py test --noinput --verbosity 0` : **344 tests
exécutés, 3 ignorés**, succès en 164 s. La recette volumétrique de cette suite
mesure 0,058 s et les mêmes 14 requêtes. `makemigrations --check --dry-run` ne
détecte aucun changement de modèle ; `git diff --check` ne signale aucune erreur.

La recette réelle PostgreSQL et la vérification visuelle navigateur ordinateur/
mobile n'ont pas pu être exécutées dans cette session. L'ORM reste commun aux
deux bases. En local, vérifier sélection automatique, basculement de chaque
filtre, navigation page 2/3 sans retour au sommet, retour d'une fiche et lisibilité
des montants sur fenêtre étroite. Aucun nouveau script n'est à exécuter au déploiement.

## Fichiers

- `reconciliation/accounting_views.py` : disponibilité et filtres de consultation.
- `templates/reconciliation/accounting_list.html`, `accounting_detail.html` : parcours et disposition.
- `templates/components/accounting_summary.html`, `accounting_table_filter.html` : composants locaux.
- `templates/components/pagination.html` : ancre optionnelle, neutre ailleurs.
- `static/css/workspace.css` : styles limités au cadrage.
- `reconciliation/test_accounting_ux.py`, `test_accounting.py` : recette et budget SQL adapté aux tests de disponibilité.

L'[inventaire des docstrings](lot3_ux_cadrage_docstrings.md) recense les 20
définitions nouvelles ou modifiées, toutes documentées en français.
