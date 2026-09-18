from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Configure le domaine des comptes et habilitations."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
