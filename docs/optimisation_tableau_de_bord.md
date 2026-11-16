# Optimisation ciblée du tableau de bord

## Cause et correctif

`dashboard.views.index` réutilise `reconciliation.review_views.visible`, qui
précharge les campagnes courante et d'origine pour les écrans de revue. Depuis
l'ajout des départements et pôles, leur champ `metadata` est devenu volumineux.
Le tableau de bord n'utilise pas ces JSON, mais les rechargeait et désérialisait
pour chaque décision passée dans `is_current()`.

La campagne locale contient 11 216 décisions versionnées et un en-tête d'environ
280 Ko. Les deux relations répètent cet en-tête, soit environ 6,3 Go transférés
vers Python avant décodage. Le nombre de requêtes n'est pas le problème principal.

Le seul changement fonctionnel de code est une projection locale à la vue :

```python
items = visible(request.user).defer("campaign__metadata", "validation_origin__metadata")
```

Les preuves utiles restent chargées, les décisions restent parcourues avec
`iterator(chunk_size=500)`, et `is_current()` est appelé exactement comme avant.
L'agrégation des décisions de version zéro, les permissions, les projets actifs,
le filtre projet, la sélection de campagne et tous les calculs sont inchangés.
Le QuerySet partagé `visible` n'est pas modifié : les autres écrans conservent
leurs métadonnées. Aucun cache, migration, modèle ou traitement asynchrone ajouté.

## Vérification

`dashboard/tests.py` compare la réponse réelle avant/après, en neutralisant
uniquement `defer` pour reproduire le comportement antérieur. Cas couverts :
validées/refusées/brouillons, décisions obsolètes, changement de montant ou de
preuve, utilisateur restreint/admin, projet interdit, campagne courante,
campagnes cachées/historiques, absence de portefeuille et compatibilité sans
campagne. Les fixtures contiennent Département, Pôle et historique BAP, ainsi
que des métadonnées de 280 Ko.

Le test SQL vérifie que les deux champs metadata sont absents de la requête
optimisée, sans lecture différée par ligne, avec le même nombre de requêtes.
Il vérifie aussi que `visible` reste inchangé pour les autres vues.

Tests exécutés depuis `app-suivi-reconciliation` :

```powershell
../.venv/Scripts/python.exe manage.py test dashboard reconciliation.test_ui reconciliation.test_review reconciliation.test_campaigns --noinput
```

Résultat : **46 tests réussis sous SQLite**, puis les **5 tests dashboard** ont
été rejoués après ajout du cas de réimport réel (47 cas distincts couverts).
Ce dernier vérifie qu'une validation fraîche devient obsolète après réimport
d'une ligne dont la source a changé. PostgreSQL réel n'était pas disponible
pour cette validation ; la projection utilise exclusivement l'ORM portable Django.
Ruff et `git diff --check` passent. Aucune modification de schéma, de JSONL ou
de données n'est nécessaire.

## Mesures

Les mesures sont obtenues sur la même base SQLite locale, le même administrateur
et le même périmètre global, en lecture seule. Deux processus neufs sont utilisés
pour mesurer séparément le pic mémoire. L'authentification est injectée dans le
processus de diagnostic pour ne pas créer de session : aucune écriture source.
Le GET passe par les middleware et le vrai template au moyen du TestClient
Django ; il ne mesure ni réseau, ni navigateur, ni infrastructure Onyxia.

Le calcul est chronométré de la sélection des lignes jusqu'à l'appel du rendu,
le rendu est mesuré séparément, et le temps HTTP local couvre toute la requête.
Le décodage JSON est instrumenté sans conserver les valeurs. Le temps SQL
`execute` exclut le fetch et ne doit pas être additionné aux temps englobants.
Le pic mémoire est le PeakWorkingSetSize Windows du processus, pas seulement la
mémoire des objets du tableau de bord.

Mesure isolée du 16 novembre 2026, sans autre test lancé en parallèle :

| Mesure | Avant | Après |
|---|---:|---:|
| Calcul des indicateurs | 50,847 s | 3,244 s |
| Rendu du template | 0,178 s | 0,095 s |
| Réponse HTTP locale, middleware inclus | 51,123 s | 3,423 s |
| Requêtes SQL | 6 | 6 |
| Exécution SQL, hors fetch | 0,029 s | 0,026 s |
| Décodage JSON | 43,644 s | 0,374 s |
| JSON décodé, octets cumulés | 6 319 890 532 | 24 618 916 |
| Pic mémoire du processus | 1 079,25 Mio | 85,77 Mio |
| Projets | 1 568 | 1 568 |
| Lignes Atlas suivies | 14 303 | 14 303 |
| Validées | 11 216 | 11 216 |
| Refusées | 0 | 0 |
| Brouillons à examiner | 3 087 | 3 087 |
| À réexaminer après changement des sources | 0 | 0 |
| À examiner, total | 3 087 | 3 087 |
| Pourcentage de validation | 78 % | 78 % |

L'instrument vérifie automatiquement l'égalité exacte des indicateurs. Les
comparaisons unitaires couvrent en complément les refus et décisions obsolètes,
absents du périmètre réel mesuré. Le rendu inclut la liste des projets ; le
volume JSON cumule tous les champs JSON décodés de cette requête, pas seulement
les deux metadata retirés. Aucun contenu JSON ni nom d'utilisateur n'est conservé
dans le rapport de métriques.

Les relevés détaillés et le script opt-in sont dans
`benchmarks/dashboard-http-report.json` et `benchmarks/dashboard_http_readonly.py`
(artefacts locaux ignorés par Git). Ces instruments ne sont pas intégrés à
l'application.

Les premières mesures d'investigation (48,7 s de parcours contre 4,1 s) ne
représentaient pas une réponse HTTP et ne constituent pas une promesse de durée.
Les chiffres instrumentés restent des mesures locales ponctuelles ; PostgreSQL
et le temps observé en production peuvent différer.

## Livraison

Fichiers applicatifs : `dashboard/views.py` (projection et docstring française),
`dashboard/tests.py` (non-régression). Redéployer l'application avec le code mis à
jour ; aucun réimport, recalcul de campagne ou migration requis pour ce correctif.
