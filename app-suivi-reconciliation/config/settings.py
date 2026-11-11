"""Configuration Django, pilotée par variables d'environnement."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Le contrat pur est partagé avec le moteur du même dépôt, sans importer pandas.
sys.path.append(str(BASE_DIR.parent))
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "cle-locale-a-remplacer")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
# Politique simple : chaque campagne SQLite complète justifie des statistiques fraîches.
# Aucun seuil de volume arbitraire ; les actions métier ne déclenchent pas ce service.
SQLITE_STATISTICS_AUTO = os.getenv("SQLITE_STATISTICS_AUTO", "true").lower() == "true"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"statistics_console": {"class": "logging.StreamHandler"}},
    "loggers": {"reconciliation.sqlite_statistics": {
        "handlers": ["statistics_console"], "level": "INFO", "propagate": False}},
}
ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
]

CSRF_TRUSTED_ORIGINS = [
    "https://user-hdkaramoko-807581-0.user.lab.sspcloud.fr",
    "https://rappro-sage-atlas.lab.sspcloud.fr",
    "https://rappro-sage-atlas-dev.lab.sspcloud.fr",
    "https://rappro-sage-atlas-preprod.lab.sspcloud.fr",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "accounts",
    "projects",
    "reconciliation",
    "imports_app",
    "dashboard",
    "maintenance",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "maintenance.middleware.MaintenanceSafeSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "maintenance.middleware.MaintenanceMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"

if os.getenv("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.getenv("POSTGRES_USER", "postgres"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {"timeout": 30},
        }
    }

AUTH_PASSWORD_VALIDATORS = (
    []
    if DEBUG
    else [
        {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
        {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
        {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
        {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    ]
)
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True
FORCE_SCRIPT_NAME = os.getenv("FORCE_SCRIPT_NAME", None)
STATIC_URL = "/proxy/8000/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "login"

# Expiration après 10 minutes sans requête HTTP, renouvelée à chaque requête.
SESSION_COOKIE_AGE = 600
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

MATCHING_JOB_ROOT = BASE_DIR / "var" / "matching"
MATCHING_MAX_FILE_BYTES = 5 * 1024**3
FILE_UPLOAD_HANDLERS = ["imports_app.upload_handlers.HashedTemporaryFileUploadHandler"]
