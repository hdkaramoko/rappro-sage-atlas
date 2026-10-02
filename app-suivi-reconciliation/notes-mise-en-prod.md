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
        ==> La home page fonctionne, les autres retirent pas le proxy/8000
        ==> On ne peut pas résoudre ce problème car une solution propre nécessite d'avoir le FORCE_SCRIPT. le faisant, on empêche le login et le logout
        ==> La solution c'est de ne pas se limiter à ces détails qui sont éphémères dans notre mise en prod. C'est spécifique à Onyxia, et le déploiement résoudra cela.


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
        ==> bind signiefie faut écouter sur le port 8000
        ```
        uv run gunicorn --chdir app-suivi-reconciliation config.wsgi:application --bind 0.0.0.0:8000
        ```

+   Installation de WhiteNoise
    -   Gunicorn est le serveur applicatif et il ne gère pas les fichiers statics (css, js)
    -   L'objectif de WhiteNoise est donc de servir proprement ces fichiers
    -   Dans django, il y a deux notions :
        ==> STATIC_ROOT : Qui rassemble tous les fichiers Django pour la production
        ==> STATICFILES_DIR : Qui est le répertoire sur disque des fichiers statics
        ==> A ce stade on a :
            ```
            STATICFILES_DIRS = [BASE_DIR / "static"]
            STATIC_ROOT = BASE_DIR / "staticfiles"
            ```
    -   Nous allons regrouper tous ces fichiers statics dans un répertoire dédié :
        ==> WhiteNoise interviendra à ce stade et permettra à Django de servir lui même les fichiers statics
        ==> L'alternative aurait été d'installer nginx pour le faire
        ==> Installation :
            ```
            uv add whitenoise
            ```
        ==> Il faut ensuite s'assurer que WhiteNoise est autorisé parmi les middlewares de Django
        ==> On va déclarer WhiteNoise comme point d'entrée pour nos statics
            ```
            STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
            ```
        ==> Commande :
            ```
            uv run python app-suivi-reconciliation/manage.py collectstatic
            ```
        ==> Cette commande va créer un répertoire staticfiles qui va regrouper tous les fichiers statics et y ajouter d'autres éléments

