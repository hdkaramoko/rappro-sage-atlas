from django.urls import path

from . import views

app_name = "projects"
urlpatterns = [
    path("portefeuille/", views.portfolio, name="portfolio"),
    path("portefeuille/<int:pk>/retirer/", views.portfolio_remove, name="portfolio_remove"),
]
