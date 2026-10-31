from django.conf import settings
from django.db import models

from zones.models import Zone


class SavedRoute(models.Model):
    """A named pickup/dropoff pair belonging to one account."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_routes"
    )
    name = models.CharField(max_length=50)
    pickup_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="saved_routes_from"
    )
    dropoff_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="saved_routes_to"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "zones_savedroute"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_user_route_name"
            )
        ]

    def __str__(self):
        return self.name


DAY_CHOICES = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


class TripPlan(models.Model):
    """US17 #46: a saved "Leave by" plan. Only the inputs are stored; the
    result is recalculated from route_hour_stats every time it is shown."""

    ARRIVE_BY = "arrive_by"
    CHEAPEST = "cheapest"
    MODE_CHOICES = [
        (ARRIVE_BY, "Arrive by"),
        (CHEAPEST, "Cheapest in the next 3 hours"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trip_plans"
    )
    name = models.CharField(max_length=50)
    pickup_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="trip_plans_from"
    )
    dropoff_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="trip_plans_to"
    )
    mode = models.CharField(max_length=20, choices=MODE_CHOICES)
    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    # The arrival time for "Arrive by", the start time for "Cheapest".
    time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_user_plan_name"
            )
        ]

    def __str__(self):
        return self.name

    @property
    def time_label(self):
        return self.time.strftime("%H:%M")
