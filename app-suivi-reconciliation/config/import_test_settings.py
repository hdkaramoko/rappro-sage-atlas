"""Bases de test isolées, sans réutiliser la connexion du .env métier."""

from .settings import *  # noqa: F403

if os.getenv("IMPORT_TEST_POSTGRES") == "1":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.getenv("IMPORT_TEST_HOST", "127.0.0.1"),
        "PORT": os.getenv("IMPORT_TEST_PORT", "5432"),
        "NAME": os.getenv("IMPORT_TEST_DB", "imports"),
        "USER": os.getenv("IMPORT_TEST_USER", "imports"),
        "PASSWORD": os.getenv("IMPORT_TEST_PASSWORD", "imports"),
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
MATCHING_JOB_RUNNER = "local"
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
