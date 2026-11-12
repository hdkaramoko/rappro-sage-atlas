from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.urls import path
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import User
from .user_import import can_import_users
from .user_import_views import UserImportMemoryHandler, import_users


@admin.register(User)
class GeographyUserAdmin(UserAdmin):
    """Expose la géographie dans l'administration des comptes."""

    fieldsets = UserAdmin.fieldsets + (("Périmètre métier", {"fields": ("geography",)}),)
    list_display = (*UserAdmin.list_display, "geography")
    change_list_template = "admin/accounts/user_change_list.html"

    def get_urls(self):
        """Ajoute l'import avant les routes utilisateur ; conserve tous les droits Admin existants."""
        return [path("import-excel/", self.admin_site.admin_view(self.import_entry), name="accounts-user-import")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        """Ajoute uniquement la visibilité du bouton selon la permission existante de création."""
        return super().changelist_view(request, {**(extra_context or {}), "can_import_users": can_import_users(request.user)})

    @method_decorator(csrf_exempt)
    def import_entry(self, request):
        """Installe le handler RAM avant l'analyse CSRF, puis appelle la vue impérativement protégée.

        L'exemption de cette enveloppe ne concerne pas le traitement final :
        import_users exécute csrf_protect après configuration des handlers.
        """
        if not can_import_users(request.user):
            raise PermissionDenied
        request.upload_handlers = [UserImportMemoryHandler(request)]
        return import_users(request)
