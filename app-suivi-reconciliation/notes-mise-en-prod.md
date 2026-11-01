# Mise en production de l'application de reconciliation

## Etape 1 : Vréifier les chemins relatifs de l'pplication

## Etape 2 : Préparer Django pour une mise en production
+   Configuration
    -   DEBUG = False
    -   ALLOWED_HOSTS = []
    -   SECRET_KEY = os.environ["]
+   Installation de l'application via un service vscode sur le sspcloud
    -   Problème sur les fichier statics : onyxia les servt via un sous chemin
        ==> Correction :
        ```
        STATIC_URL = "/proxy/8000/static/"
        ```

        ```
        from django.conf import settings
        from django.contrib.staticfiles.views import serve
        from django.urls import re_path

        if settings.DEBUG:
            urlpatterns += [
                re_path(r"^static/(?P<path>.*)$", serve),
            ]
        ```
    -   Problème de ALLOWED_HOST et connexion à l'application lié au CSRF:

        ```
        CSRF_TRUSTED_ORIGINS = [
            "https://user-hdkaramoko-807581-0.user.lab.sspcloud.fr",
        ]
        ```
    -   Création d'un superuser
    -   Problème de navigation
        *   La home page fonctionne, les autres retirent pas le proxy/8000
        *   On ne peut pas résoudre ce problème car une solution propre nécessite d'avoir le FORCE_SCRIPT. le faisant, on empêche le login et le logout
        *   La solution c'est de ne pas se limiter à ces détails qui sont éphémères dans notre mise en prod. C'est spécifique à Onyxia, et le déploiement résoudra cela.


+   Installation de Gunicorn
    -   Gunicorn est un serveur applicatif qui permet de faire tourner WSGI
    -   L'utilisateur se connecte à son navigateur (client) et envoie uen requête qui passe par un reverse proxy
    -   Gunicorn est celui qui reçoit les requêtes et les transmets à django et fait le sens inverse aussi
    -   Il gère plusieurs processus /workers pour servir l'appli proprement.
    -   WSGI c'est ce qui fait l'interface (traducteur) entre Gunicorn et Django
    -   Installation :
        ```
        uv add gunicorn
        ```
    -   Lancement de gunicorn
        *   bind signiefie faut écouter sur le port 8000
        ```
        uv run gunicorn --chdir app-suivi-reconciliation config.wsgi:application --bind 0.0.0.0:8000
        ```

+   Installation de WhiteNoise
    -   Gunicorn est le serveur applicatif et il ne gère pas les fichiers statics (css, js)
    -   L'objectif de WhiteNoise est donc de servir proprement ces fichiers
    -   Dans django, il y a deux notions :
        *   STATIC_ROOT : Qui rassemble tous les fichiers Django pour la production
        *   STATICFILES_DIR : Qui est le répertoire sur disque des fichiers statics
        *   A ce stade on a :
            ```
            STATICFILES_DIRS = [BASE_DIR / "static"]
            STATIC_ROOT = BASE_DIR / "staticfiles"
            ```
    -   Nous allons regrouper tous ces fichiers statics dans un répertoire dédié :
        *   WhiteNoise interviendra à ce stade et permettra à Django de servir lui même les fichiers statics
        *   L'alternative aurait été d'installer nginx pour le faire
        *   Installation :
            ```
            uv add whitenoise
            ```
        *   Il faut ensuite s'assurer que WhiteNoise est autorisé parmi les middlewares de Django
        *   On va déclarer WhiteNoise comme point d'entrée pour nos statics
            ```
            STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
            ```
        *   Commande :
            ```
            uv run python app-suivi-reconciliation/manage.py collectstatic
            ```
        *   Cette commande va créer un répertoire staticfiles qui va regrouper tous les fichiers statics et y ajouter d'autres éléments


+   [Alternative-1] Dockerisation de l'application
    -   Le but de la Dockerisation est de constituer uen image autonome de l'application qui va contenir :
        *   Mon code
        *   Python
        *   Les dépendances
        *   Gunicorn
        *   Les fichiers statics collectés
    -   Docker c'est un système à part qui se charge du build de l'application. Il ne s'installe pas dans le venv
    -   On commence par créer un dockerfile à la racine du repo :
        *   C'est un fichier sans extension
        *   Avec une structure stable : Base --> Dossier de travail --> Dépendances --> Code --> Préparation --> Port --> Commande de démarrage
    -   On crée ensuite un .dockerignore pour les fichiers qui doivent être ignorés
    -   Dans le terminal, on va ensuite lancer le build de l'application avec la commande
        ```
        docker build -t rapproche-sage-atlas:0.1
        ```
    -   Dans la mesure ou docker n'est pas disponible sur onyxia, on va faire le build avec github dans une logique de CI


+   [Alternative-2] On automatise la construction de l'image docker
    -   En fait, github dans sa chanie de CI met à disposition une machine virtuelle et temporaire sur laquelle docker est installée
    -   C'est l'intégration continue
    -   On fait en sorte que à chaque push sur la branche main -> Github Actions démarre une VM Ubuntu -> Docker construit l'image -> L'image est poussée dans GHCR
    -   Du coup, cela n'exonère pas de créer le dockerfile. Il faut le faire anyway
    -   Les étapes :
        *   Créer le dockerfile et le .dockerignore
        *   Créer un dossier .github/workflows/docker.yml
        *   Déclencher le workflow en envoyant un commit du code : git add -> git commit -> git push
        *   On peut alors aller sur github, dans package et voir l'url du package qui a été créé : ghcr.io/hdkaramoko/rappro-sage-atlas:0.1 (référence de l'image)

+   Déploiement depuis kubernetes sur onyxia
    -   On s'addure que le service vscode quo'n a démarré c'est bien en mode admin
    -   On crée un répertoire k8s et un fichier deployment.yaml à l'intérieur
    -   Le package étant privé, il faut une connexion entre kubernetes et le registry
    -   Créer dans github un Personal Access Token GitHub (PATG) : onyxia-ghcr-rappro-sage-atlas
        -> Settings --> developer settings --> personnal access token --> Token classic -> Générer new token classic -> Note = nom -> Read package -> Validité
    -   Créer un secret pour permettre la connexion entre kubernetes et le docker registry
        ```
        kubectl create secret docker-registry ghcr-secret \
        --docker-server=ghcr.io \
        --docker-username=TON_USER_GITHUB \
        --docker-password=TON_TOKEN_GITHUB \
        --namespace=NAMESPACE
        ```
    -   Faire la commande : kubectl apply -f k8s/deployment.yaml qui va exécuter les instruction yaml qu'on lui a fourni précédemment
    -   On peut sa'ssurer que l'application est en train de tourner si on a le statut running avec la commande : kubectl get pods
    -   On peut voir le log d'excution avec : kubectl logs -l app=rappro-sage-atlas

+   Création d'un service kubernetes pour exposer le port 8000
    -   Dans k8s, créer un fichier service.yaml
    -   Contenu a voir, mais cela précise le targetPort qui est celui écouté par gunicorn : 8000. Le service lui, écoute via le port 80
    -   On applque alors les instructions du yaml avec : kubectl apply -f k8s/service.yaml
    -   Cela crée le service
    -   On peut vérifier avec : kubectl get service rappro-sage-atlas
    -   A ce stade, ce service est accessible à l'intérieur du de kubernetes, mais pas sur internet
    -   L'étape de l'ingress permettra de mettre tout ceci à disposition

+   Créer l'ingress pour exposer l'application sur internet
    -   Création dans le dossier k8s de ingress.yaml
    -   L'ingress définit du coup le nom d'hôte : rappro-sage-atlas.lab.sspcloud.fr qui utilise le service : rappro-sage-atlas qui écoute via le port : 80
    -   On applque alors les instructions du yaml avec : kubectl apply -f k8s/ingress.yaml
    -   On peut vérifier avec : kubectl get ingress rappro-sage-atlas

+   Finalité
    -   Vérifier que le nom d'hôte est dans les django allowed host et dans les CSRF_Trusted_Origin
    -   Après chaque modification, il es nécessaire de redémarrer le pod pour qu'il prenne en compte la nouvelle image
    -   Générer une django secret key : python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
    -   Attention, la clé doit rester stable. Elle permet à Django de signer certaines actions
    -   Création d'un super user
        *   Appliquer les migrations à la BDD : kubectl exec -it deployments/rappro-sage-atlas -- sh -c 'cd /app/app-suivi-reconciliation && uv run python manage.py migrate'
        *   kubectl exec -it deployment/rappro-sage-atlas -- sh -c 'cd /app/app-suivi-reconciliation && uv run python manage.py createsuperuser'

+   Automatisation du déploiement (Pas faisable sur mon cluster qui est privé)
    -   Jusqu'ici, quand on a une nouvelle image de l'application crée depuis github actions, il fallait redéployer l'application via kubernetes :
        ```
        kubectl apply -f k8s/deployment.yaml --> pour réappliquer le déploiement
        kubectl rollout restart deployment rappro-sage-atlas --> pour forcer le déploiement si on rejoue sur un même tag
        ```
    -   Ce déploiement est donc manuel
    -   L'objectif de cette section est d'automatiser ce déploiement à travers notamment la CD (Continue Delivery)
    -   Cela consistera à donner à GITHUB la possibilité de faire kubectl apply -f sur notrecluster kubernetes
    -   Etape 1 : Créer un fichier ```github-actions-serviceaccount.yaml``` dans le dossier k8s
        *   Les commandes suivantes permettent de vérifier qu'on peut bien créer un serviceAccounts dans son namespace kubernetes
            ```
            kubectl auth can-i create serviceaccounts
            kubectl auth can-i create roles
            kubectl auth can-i create rolebindings
            ```
        *   Créer le fichier de contrat yaml
        *   Populate
        *   Appliquer ce contrat avec : ```kubectl apply -f k8s/github-actions-serviceaccount.yaml```

    -   Etape 2 : Donner au ServiceAccount les droits nécessaires (le minimum de droits)
        *   Créer un fichier ```github-actions-role.yaml``` dans k8s
        *   Populate ce fichier
        *   Créer le fichier ```github-actions-rolebinding.yaml``` dans k8s
        *   Populate
        *   Ce qui se passe c'est qu'pn crée un yaml qui définit un certain rôle (des permissions)
        *   Ensuite, on attribue ce role à un agent déployer : github-actions-deployer
        *   On applique alors le contrat de ces deux fichiers yaml:
            ```
            kubectl apply -f k8s/github-actions-role.yaml
            kubectl apply -f k8s/github-actions-rolebinding.yaml
            ```
    -   Etape 3 : Création d'un token dédié au ServiceAccount
        *   L'idée est de généer un token qui sera de kubernetes qui sera chargé dans github et permettra les va-et-viens
        *   La commande ```kubectl create token github-actions-deployer```
        *   Ce stoken sera repris par github pour authentifier ses requêtes au cluster
    
    -   Etape 4 : Faire le lien entre les services
        *   Pour établir la connexion, il faudra 3 choses : 
            1.  KUBE_SERVER = Adresse de l'API Kubernetes
            2.  KUBE_TOKEN = Identité du ServiceAccount
            3.  KUBE_CA_CERT = Certificat pour vérifier le serveur qui demande
        *   La commande ```kubectl cluster-info``` permetd'avoir l'adresse de l'API

+   Mise en place d'une branche de dev pour la preprod
    -   Création de dossiers dans k8s : dev et prod
    -   Tous les fichier des déploiement à ce stade sont basculés dans la prod
    -   On recrée les même dans le dpssier dev en rajoutant dev à la fin des name, info, etc.
    -   Il faut surtout s'assurer qu'on est sur la branche dev. Cette branche sera appliquée sur la main ultérieuement
    -   Construction des 3 manifests et application avec les commandes : 
        ```
        kubectl apply -f k8s/dev/deployment.yaml
        kubectl apply -f k8s/dev/service.yaml
        kubectl apply -f k8s/dev/ingress.yaml
        ```
    -   Coté django : rajouté la nouvelle URL aux trusted CSRF et ALLOWED_HOST
    -   A ce stade, la commande ```kubectl get pods``` donne invalidImageName car le tag indiqué dans le manifest ne correspond à rien
    -   Notons que les parties où nous avons indiquées SHA dans les manifests doivent êtremodifiées à chaque push et création image
    -   Une autre façon est de laisser cette info générique dans les manifest et d'appliquer la commande en modifiant directement :
        ```
        kubectl set image deployment/rappro-sage-atlas-dev rappro-sage-atlas-dev=ghcr.io/hdkaramoko/rappro-sage-atlas:dev-30630d3...
        ```
    -   Mais du coup le sha, on le récupère avec la commande : ```git rev-parse HEAD```
    -   Migration et création du superuser
        *   Appliquer les migrations à la BDD : kubectl exec -it deployments/rappro-sage-atlas-dev -- sh -c 'cd /app/app-suivi-reconciliation && uv run python manage.py migrate'
        *   kubectl exec -it deployment/rappro-sage-atlas-dev -- sh -c 'cd /app/app-suivi-reconciliation && uv run python manage.py createsuperuser'

## Etape 3 : Migration de la base de données SQLite vers PostgreSQL
+   Sauvegarde de la base existante :
    -   Lancer la commande : ```cp app-suivi-reconciliation/db.sqlite3 app-suivi-reconciliation/db.sqlite3.backup```
    -   Vérifier l'intégrité de la BDD : (On exécute un code python dans le terminal sans créer de fichier .py)
        ```
            python - <<'PY'
            import sqlite3

            db = sqlite3.connect("db.sqlite3")
            print(db.execute("PRAGMA integrity_check").fetchone())
            db.close()
            PY
        ```
    -   Le résultat attendu est ok (intégrité structurelle - tables, indexes, etc - référentielles - relations entre les données respectées, données - unicité, obligatoire, etc)
    -   Explication de la syntaxe :
        *   python - : permet de demander à python de lire le code qui va suivre
        *   << : c'est un opérateur du shell appelé "Here document" et qui permet de fournir plusieurs lignes de texte à une commande
        *   'PY' : délimiteur qui indique où commence et où se termine le code. Les guillemets pour empêcher le shell d'interpréter son contenu

+   Création du service PostgreSQL pour l'nevironnement de dev
    -   Copie des credentials dans les variables d'environnements du projet

+   Import du module python de connexion à postgres : ```uv add "psycopg[binary]"```

+   Adapter le fichier settings.py
    -   Articulation entre variables d'environnement et settings.py

+   Le cablage est fait à cette étape, on procède à l'évaluation de celui-ci et l'identification des migrations :
    ```
        uv run python app-suivi-reconciliation/manage.py check
        uv run python app-suivi-reconciliation/manage.py showmigrations
        uv run python app-suivi-reconciliation/manage.py migrate
    ```

+   Visualisation de la base de données depuis l'interface pgadmin
    -   Création du service pgadmin
    -   Connexion au service avec les credentials
    -   Accès bdd : autodiscovery > postgresql-cnpg-* > Bases de données > DB_NAME > Schémas > public > Tables 

+   Export des données sqlite
    -   Django prévoit une fonction d'export des données d'une BDD. Pour cela, il faut recabler sqlite et faire la syntaxe suivante 
    -   Syntaxe : 
        ```
            uv run python app-suivi-reconciliation/manage.py dumpdata \
            --natural-foreign \
            --natural-primary \
            --all \
            --exclude=contenttypes \
            --exclude=auth.Permission \
            --exclude=sessions \
            --output=app-suivi-reconciliation/data_export.json.gz
        ```
    -   Il peut arriver que cette commande ne fonctionne pas. Dans ce cas, premier réflexe, c'est de regarder les migrations. Certaines non appliquées
    -   Cabler à nouveau la BDD sur l'instance postgres
    -   Exécuter la commande suivante qui va charger les données exportées vers la nouvelle base:
        ```
            uv run python app-suivi-reconciliation/manage.py loaddata app-suivi-reconciliation/data_export.json.gz
        ```
    -   Ainsi, toutes les données de la base sqlite sont transférées vers la nouvelle base
+   Réinitialiser les séquences
    -   PostgreSQL utilise des séquences pour certaines clés primaires auto-incrémentées.
    -   L'objectif est donc de réinitialiser ces séquences pour éviter des collisions
    -   On le fait pour toutes les applications déclarées dans le projet django
    -   La syntaxe :
        ```
            uv run python app-suivi-reconciliation/manage.py sqlsequencereset accounts
            uv run python app-suivi-reconciliation/manage.py sqlsequencereset projects
            uv run python app-suivi-reconciliation/manage.py sqlsequencereset reconciliation
            uv run python app-suivi-reconciliation/manage.py sqlsequencereset imports_app
            uv run python app-suivi-reconciliation/manage.py sqlsequencereset dashboard
        ```
+   Modification du manifest de déploiement
    -   Rajout des éléments de connexion de la DB au manifest
    -   Initialiser postgresql avec la syntaxe de migration : ```uv run python app-suivi-reconciliation/manage.py migrate```
    -   Appliquer le nouveau déploiement du pod - attention, il faut récupérer le sha de l'ancien
        ```
            kubectl apply -f k8s/dev/deployment.yaml
            kubectl set image deployment/rappro-sage-atlas-dev rappro-sage-atlas-dev=ghcr.io/hdkaramoko/rappro-sage-atlas:dev-<SHA>
            kubectl rollout status deployment/rappro-sage-atlas-dev -n user-hdkaramoko --timeout=120s
        ```
    -   Faire les migrations
        