# Synthèse du cadrage : présentation compacte v2

**Périmètre actualisé le 12 novembre 2026 :** les Sage sans Atlas sont inclus et
filtrables avec les écarts. Seuls les types explicitement exclus sont hors
périmètre. Voir le [cadrage exhaustif et le diagnostic ODA](cadrage_exhaustif_oda.md).

Le décalage provenait notamment du style global `dl { display:grid;
grid-template-columns:1fr 2fr }`, qui plaçait des montants dans une colonne
distincte de leur libellé. La synthèse neutralise maintenant cette règle dans
son seul périmètre : chaque liste d'indicateur est en flux vertical, aligné
à gauche, sans modifier les autres écrans.

Le composant suit trois niveaux :

1. Deux cartes de référence de même largeur : Atlas initial avec Comptabilisé
   et Envoyé SAGE initial, puis Sage retenu sans décomposition.
2. Deux cartes de résultat : Atlas retenu pour le cadrage, puis écart global
   avec le badge courant. Les quatre valeurs principales utilisent la même
   échelle typographique, des chiffres tabulaires et des marges réduites.
3. Les quatre informations complémentaires sont en quatre colonnes sur écran
   large et deux sur fenêtre plus étroite. Les deux rangées principales passent
   sur une colonne sur mobile ; les grands montants peuvent revenir à la ligne.

L'accordéon de périmètre, l'identification de campagne, les badges et le texte
sur les écarts compensés sont conservés. Ce dernier est plus discret. Les filtres,
la pagination et les retours de la v1 restent inchangés.

## Fichiers de cette v2

- `templates/components/accounting_summary.html` : nouvelle disposition ; mêmes
  champs et filtres monétaires.
- `static/css/workspace.css` : suppression des anciens styles de synthèse,
  correction locale du comportement des dl et grille responsive compacte.
- `templates/reconciliation/accounting_detail.html` : texte explicatif secondaire.

Aucun modèle, service, vue Python, JavaScript, formule, montant ou règle n'a été
modifié pour cette v2. Aucune fonction ou méthode n'a été créée ou modifiée ;
les commentaires CSS et cette documentation expliquent les choix de présentation.

## Vérification

```powershell
python manage.py test reconciliation.test_accounting_ux reconciliation.test_accounting --noinput --verbosity 0
```

**20 tests réussis** : conservation des montants et états, valeurs négatives,
corrections, confirmations, ODS/ODG, filtres et navigation. `git diff --check` ne
signale aucune erreur. Aucun nouveau test reflétant simplement les classes CSS
n'a été ajouté.

La vérification visuelle interactive n'a pas pu être exécutée : aucun navigateur
pilotable ni runtime Playwright/Selenium n'est disponible dans cette session.
Recette à effectuer sur ordinateur et fenêtre mobile : valeurs immédiatement
sous leur libellé, alignement à gauche, quatre indicateurs principaux lisibles,
grands montants sans débordement, informations secondaires compactes et accordéon
fonctionnel. Aucun recalcul, nouveau JSONL ou migration n'est nécessaire.
