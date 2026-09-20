from django.urls import path
from django.views.generic import RedirectView

from . import campaign_views, review_views

app_name = "reconciliation"
urlpatterns = [
    path("campagnes/", campaign_views.campaign_list, name="campaigns"),
    path("campagnes/<int:pk>/", campaign_views.campaign_detail, name="campaign"),
    path("campagnes/<int:pk>/export/", campaign_views.campaign_export, name="campaign-export"),
    path("campagnes/lignes/<int:pk>/", campaign_views.campaign_review, name="campaign-review"),
    path("validation/", review_views.review_list, name="reviews"),
    path("validation/export/", review_views.conservation_export, name="conservation-export"),
    path("validation/<int:pk>/", review_views.review_detail, name="review-detail"),
    path("", RedirectView.as_view(pattern_name="reconciliation:reviews", query_string=True)),
]
