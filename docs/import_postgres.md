# Imports JSONL volumineux sur PostgreSQL

Le formulaire conserve le fichier, enregistre un traitement puis lance
`run_matching_job` dans un processus indépendant de Gunicorn. Le transfert HTTP
doit se terminer avant l'affichage du suivi ; le chargement métier s'effectue
ensuite en arrière-plan.

## Déploiement

- Renseigner `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`
  et `POSTGRES_PORT`, puis exécuter `python manage.py migrate`.
- Définir `DJANGO_DEBUG=False` (la variable `DEBUG` seule n'est pas utilisée).
  Les commandes d'import désactivent également le debug pour éviter la rétention
  des requêtes SQL et de leurs paramètres JSON en mémoire.
- Appliquer les manifestes Ingress actualisés : taille maximale de requête
  de 5 Go plus la marge multipart, délais de transmission et de réponse de
  600 secondes. Vérifier les limites du proxy éventuellement placé en amont.
  Référence : [annotations Ingress NGINX](https://kubernetes.github.io/ingress-nginx/user-guide/nginx-configuration/annotations/).
- Conserver `var/matching` sur un volume persistant. Si plusieurs pods servent
  l'application, ils doivent partager les fichiers de suivi et les JSONL.
  Un processus détaché survit à la requête, mais pas à l'arrêt de son conteneur.

## Garanties et coûts

L'empreinte est calculée pendant la réception puis revérifiée par le worker.
Sur Linux et sur le même volume, le fichier temporaire est renommé sans seconde
copie. Sur Windows ou entre volumes, une copie reste nécessaire.

Un verrou consultatif PostgreSQL de session sérialise les imports, y compris
ceux lancés en ligne de commande ou depuis un autre pod. Il est libéré à la fin
du traitement et lorsque PostgreSQL détecte la déconnexion du processus.
Ce mécanisme requiert une connexion stable : avec PgBouncer, utiliser un accès
direct ou le mode de pooling par session pour les workers.

Inventaires, contrôles et photographies des propositions sont insérés par lots.
Les projets sont réutilisés pendant l'import ; les validations lisent les
photographies progressivement, et le traitement collectif conserve des
identifiants plutôt que toutes les preuves en mémoire. Les contrôles métier et
le report des décisions restent appliqués.

La transaction PostgreSQL englobe toute la campagne : une erreur tardive annule
également les lots déjà insérés. Elle peut retenir les verrous des lignes
concernées pendant le traitement. Les phases et compteurs sont suivis dans
`progress.json` et `import.log`, sans attendre le commit de la transaction.
Les exceptions complètes sont conservées dans `worker.log`.

## Relancer après une interruption

Vérifier d'abord que le worker est réellement arrêté et conserver son répertoire
de fichiers. Depuis le même environnement et avec la même configuration :

```sh
python manage.py run_matching_job <uuid-du-traitement> --resume
```

Cette commande recommence un traitement actif interrompu depuis le début ; elle
ne reprend pas au dernier lot. Un traitement marqué `FAILED` doit être soumis
à nouveau. Le même fichier déjà publié est détecté comme doublon.

Pour un fichier déjà présent sur le serveur, on peut éviter le transfert HTTP :

```sh
python manage.py import_review_bundle /chemin/campagne_30102026.jsonl
```

Cette commande est synchrone et ne crée pas de ligne de suivi `MatchingJob`.
Ne pas exécuter `prepare_sqlite_imports` sur PostgreSQL.

## Vérification du 1er novembre 2026

Le fichier `data/outputs/campagne_30102026.jsonl` (534 535 510 octets) a été
importé intégralement dans une base SQLite de test isolée, via le parcours ORM
utilisé pour PostgreSQL : 342 910 observations d'inventaire, 12 548 groupes et
243 561 contrôles. Publication réussie en 851,53 secondes (environ 14 minutes),
avec une mémoire observée autour de 100 Mo. Ce temps local n'est pas un
benchmark PostgreSQL et ne mesure pas le transfert HTTP.

La sélection de tests ciblés comporte 90 réussites et un test d'intégration
PostgreSQL ignoré, faute d'instance disponible. Les deux scénarios en échec dans
la suite complète ont été reproduits sur le code d'origine : compatibilité
d'un en-tête historique v2 avec le mode collectif ACTIVE et scénarios de
publication SQLite (concurrence et reprise d'une décision historique).
