# Informations Atlas complémentaires pour la validation

Trois champs sources sont affichés en lecture seule dans la vue de validation :
**Montant refacturables**, **Prix unitaire prévu** et **Nombre d'unités**.
L'en-tête réel `Montant refacturable (€)` du JDD est reconnu comme alias du premier.
`Nb unités prévues` n'est pas utilisé : la demande concerne `Nombre d'unités`.

## Cheminement technique

1. Le chargeur Atlas lit les nombres décimaux français, y compris les espaces
   insécables. Le contrat partagé `reconciliation_contract.atlas_context` produit
   une représentation stable, sans passage par un flottant ni arrondi aux centimes.
   Les valeurs absentes deviennent `null`, zéro reste zéro. Six décimales maximum
   sont acceptées ; les valeurs invalides, non finies ou trop précises sont refusées.
2. Le JSONL de rapprochement enrichit inventaire et propositions, en formats v2 et v3.
   Les règles de matching et de contrôle des multiples ne sont pas modifiées.
   Les preuves de multiples gardent leur schéma antérieur ; le contrôle serveur
   distingue ces preuves du contexte supplémentaire de validation.
3. L'application vérifie la concordance de ces champs entre inventaire et proposition.
   Trois colonnes `DecimalField`, nullables, sont ajoutées aux sources courantes par
   la migration `0012_atlas_validation_context`. Les photographies et événements
   conservent les valeurs de leur époque, avec leur précision.
4. L'empreinte de validation et celle des membres du groupe incluent ces données.
   Une modification, une disparition ou l'apparition d'une valeur impose un
   réexamen ; les différences indiquent le champ concerné. Une modification d'un
   membre peut aussi invalider la validation de ses voisins du même groupe,
   conformément au fonctionnement existant des montants.
5. Les anciennes valeurs restent visibles dans la campagne historique. L'export
   JSON de la base inclut automatiquement les colonnes et les photographies.

Les nouveaux champs sont informatifs et ne sont pas proposés comme corrections
manuelles. Le format du fichier de conservation et les colonnes canoniques de
l'Excel du moteur restent inchangés.

## Anciennes campagnes et installation

Les anciens fichiers JSONL restent importables : champs absents = valeurs nulles.
Les champs tous absents ne sont pas ajoutés à l'empreinte, afin de ne pas invalider
une ancienne validation uniquement parce que le logiciel a été mis à jour.
La première campagne apportant de nouvelles valeurs pourra en revanche nécessiter
un réexamen : ce sont de nouvelles informations déterminantes.

Après déploiement du moteur, du contrat partagé et de l'application, depuis
`app-suivi-reconciliation`, hors import en cours :

```powershell
uv sync
uv run python manage.py prepare_sqlite_imports --migrate
```

La commande sauvegarde SQLite avant migration et refuse un import encore actif.
Redémarrer ensuite le serveur. Sur une base PostgreSQL, utiliser `manage.py migrate`.
Un **nouveau rapprochement** est nécessaire pour alimenter les champs : une ancienne
extraction JSONL ne contient pas ces informations et ne peut pas les reconstituer.

## Vérifications

Tests de lecture du véritable intitulé Atlas sur un classeur synthétique, export
v2/v3, distinction zéro/absent, précision à six décimales, rejet des nombres
invalides, cohérence inventaire/proposition, report inchangé et réexamen pour
chacun des trois champs, affichage, historique et compatibilité des contrôles v3.

Vérification du 12 octobre 2026 : 123 tests moteur réussis (1 ignoré), 93 tests
application réussis (1 test PostgreSQL ignoré). Migration 0012 appliquée localement
après sauvegarde dans `app-suivi-reconciliation/var/backups/`. Aucun rapprochement
réel n'a été relancé. WhiteNoise, déjà activé dans les paramètres de l'application,
a aussi été déclaré dans ses propres dépendances pour permettre une installation
et une exécution des tests cohérentes.
