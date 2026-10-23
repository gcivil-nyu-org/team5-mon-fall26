from django.urls import path

from . import views

app_name = "zones"

urlpatterns = [
    path("", views.map_view, name="map"),
    path("api/zones", views.zones_api, name="zones_api"),
    path("api/zones/<int:zone_id>/heatmap", views.heatmap_api, name="heatmap_api"),
    path("api/routes", views.routes_api, name="routes_api"),
]
