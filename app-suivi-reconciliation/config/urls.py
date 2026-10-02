"""Routage principal de l'application."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.staticfiles.views import serve
from django.urls import include, path, re_path
from . import settings


urlpatterns = [
    path("imports/", include("imports_app.urls")),
    path("admin/", admin.site.urls),
    path(
        "connexion/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("deconnexion/", auth_views.LogoutView.as_view(next_page="../connexion/"), name="logout"),
    path("", include("dashboard.urls")),
    path("projets/", include("projects.urls")),
    path("rapprochements/", include("reconciliation.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        re_path(r"^static/(?P<path>.*)$", serve),
    ]
