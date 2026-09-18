from django.urls import path

from . import views

app_name = "imports"
urlpatterns = [
    path("", views.index, name="index"),
    path("<uuid:pk>/", views.detail, name="detail"),
    path("<uuid:pk>/fichiers/<str:artifact>/", views.download, name="download"),
]
