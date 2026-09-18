from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    """Configure le domaine des projets."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "projects"
