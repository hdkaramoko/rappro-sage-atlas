# Mise en production de l'application de reconciliation

## Etape 1 : Vréifier les chemins relatifs de l'pplication

## Etape 2 : Préparer Django pour une mise en production
+   Configuration
    -   DEBUG = False
    -   ALLOWED_HOSTS = []
    -   SECRET_KEY = os.environ["]
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