from django.urls import path

from . import views

app_name = "routes"

urlpatterns = [
    path("api/routes/leave-by", views.leave_by_api, name="leave_by_api"),
    path("api/routes/cheapest", views.cheapest_api, name="cheapest_api"),
    path("api/routes/nearby", views.nearby_api, name="nearby_api"),
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
    path(
        "plans/<int:plan_id>/calendar.ics",
        views.plan_calendar_ics,
        name="plan_calendar",
    ),
    path("plans/<int:plan_id>/edit/", views.edit_plan, name="edit_plan"),
    path("plans/<int:plan_id>/delete/", views.delete_plan, name="delete_plan"),
    path("day-plans/save/", views.save_day_plan, name="save_day_plan"),
    path("day-plans/", views.my_day_plans, name="my_day_plans"),
    path("day-plans/<int:plan_id>/", views.open_day_plan, name="open_day_plan"),
    path(
        "day-plans/<int:plan_id>/day/",
        views.change_day_plan_day,
        name="change_day_plan_day",
    ),
    path(
        "day-plans/<int:plan_id>/stops/add/",
        views.add_day_plan_stop,
        name="add_day_plan_stop",
    ),
    path(
        "day-plans/<int:plan_id>/stops/<int:stop_id>/time/",
        views.set_day_plan_stop_time,
        name="set_day_plan_stop_time",
    ),
    path(
        "day-plans/<int:plan_id>/stops/<int:stop_id>/move/",
        views.move_day_plan_stop,
        name="move_day_plan_stop",
    ),
    path(
        "day-plans/<int:plan_id>/stops/<int:stop_id>/remove/",
        views.remove_day_plan_stop,
        name="remove_day_plan_stop",
    ),
    path(
        "day-plans/<int:plan_id>/reorder/",
        views.reorder_day_plan,
        name="reorder_day_plan",
    ),
    path(
        "day-plans/<int:plan_id>/delete/",
        views.delete_day_plan,
        name="delete_day_plan",
    ),
]
