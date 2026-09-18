from django.urls import path
from django.views.generic import RedirectView

from . import review_views

app_name = "reconciliation"
urlpatterns = [
    path("validation/", review_views.review_list, name="reviews"),
    path("validation/export/", review_views.conservation_export, name="conservation-export"),
    path("validation/<int:pk>/", review_views.review_detail, name="review-detail"),
    path("", RedirectView.as_view(pattern_name="reconciliation:reviews", query_string=True)),
]
