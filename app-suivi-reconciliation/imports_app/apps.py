from django.apps import AppConfig


class ImportsAppConfig(AppConfig):
    """Configure le pipeline d'import."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "imports_app"
