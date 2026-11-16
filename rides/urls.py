from django.urls import path

from . import views

app_name = "rides"

urlpatterns = [
    path("rides/", views.find_rides_view, name="find_rides"),
    path("rides/mine/", views.my_rides_view, name="my_rides"),
    path("rides/new/", views.post_ride, name="post_ride"),
    path("rides/<int:post_id>/", views.ride_detail, name="ride_detail"),
    path("rides/<int:post_id>/edit/", views.edit_ride, name="edit_ride"),
    path("rides/<int:post_id>/close/", views.close_ride, name="close_ride"),
    path("rides/<int:post_id>/delete/", views.delete_ride, name="delete_ride"),
    path(
        "rides/<int:post_id>/interest/",
        views.show_interest,
        name="show_interest",
    ),
    path(
        "rides/<int:post_id>/withdraw/",
        views.withdraw_interest,
        name="withdraw_interest",
    ),
    path(
        "rides/<int:post_id>/interests/<int:interest_id>/accept/",
        views.accept_interest,
        name="accept_interest",
    ),
    path(
        "rides/<int:post_id>/interests/<int:interest_id>/decline/",
        views.decline_interest,
        name="decline_interest",
    ),
    path(
        "rides/<int:post_id>/interests/<int:interest_id>/undo-acceptance/",
        views.undo_acceptance,
        name="undo_acceptance",
    ),
    path(
        "rides/<int:post_id>/messages/<int:rider_id>/",
        views.conversation,
        name="conversation",
    ),
    path(
        "rides/<int:post_id>/messages/<int:rider_id>/new/",
        views.conversation_updates,
        name="conversation_updates",
    ),
]
