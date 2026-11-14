from django.urls import path

from . import views

app_name = "rides"

# /rides/mine/ is US37 #99.
urlpatterns = [
    path("rides/", views.find_rides_view, name="find_rides"),
    path("rides/new/", views.post_ride, name="post_ride"),
    path("rides/<int:post_id>/", views.ride_detail, name="ride_detail"),
]
