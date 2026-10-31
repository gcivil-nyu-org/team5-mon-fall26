from django.urls import path

from . import views

app_name = "routes"

urlpatterns = [
    path("api/routes/leave-by", views.leave_by_api, name="leave_by_api"),
    path("api/routes/cheapest", views.cheapest_api, name="cheapest_api"),
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
    path("plans/save/", views.save_plan, name="save_plan"),
    path("plans/", views.my_plans, name="my_plans"),
    path("plans/<int:plan_id>/", views.open_plan, name="open_plan"),
    path("plans/<int:plan_id>/edit/", views.edit_plan, name="edit_plan"),
    path("plans/<int:plan_id>/delete/", views.delete_plan, name="delete_plan"),
]
