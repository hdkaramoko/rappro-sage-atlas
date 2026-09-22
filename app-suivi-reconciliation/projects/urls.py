from django.urls import path

from . import views

app_name = "projects"
urlpatterns = [
    path("portefeuilles/import/", views.portfolio_import, name="portfolio-import"),
    path("portefeuilles/modele/", views.portfolio_template, name="portfolio-template"),
    path("portefeuille/", views.portfolio, name="portfolio"),
    path("portefeuille/<int:pk>/retirer/", views.portfolio_remove, name="portfolio_remove"),
]
