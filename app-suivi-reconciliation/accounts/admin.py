from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class GeographyUserAdmin(UserAdmin):
    """Expose la géographie dans l'administration des comptes."""

    fieldsets = UserAdmin.fieldsets + (("Périmètre métier", {"fields": ("geography",)}),)
    list_display = (*UserAdmin.list_display, "geography")
