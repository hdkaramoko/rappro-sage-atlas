from django.contrib import admin

from .models import Project, ProjectPortfolio


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Facilite la maintenance du référentiel projet."""

    list_display = ("code", "label", "geography", "is_active", "updated_at")
    list_filter = ("geography", "is_active")
    search_fields = ("code", "label")


@admin.register(ProjectPortfolio)
class ProjectPortfolioAdmin(admin.ModelAdmin):
    """Expose les habilitations simples par portefeuille."""

    list_display = ("user", "project", "created_at")
    search_fields = ("user__username", "project__code")
