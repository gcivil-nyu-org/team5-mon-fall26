from django.urls import path

from . import views

app_name = "routes"

urlpatterns = [
    path("saved-routes/save/", views.save_route, name="save_route"),
    path("saved-routes/", views.my_routes, name="my_routes"),
    path(
        "saved-routes/<int:route_id>/open/",
        views.open_saved_route,
        name="open_saved_route",
    ),
    path(
        "saved-routes/<int:route_id>/rename/",
        views.rename_saved_route,
        name="rename_saved_route",
    ),
    path(
        "saved-routes/<int:route_id>/delete/",
        views.delete_saved_route,
        name="delete_saved_route",
    ),
]
