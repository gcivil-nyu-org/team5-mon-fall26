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


class DayPlan(models.Model):
    """US20 #49: a day of trips as an ordered chain of stops. Leg i runs
    from stop i to stop i+1 and leaves at stop i's leave time."""

    MIN_STOPS = 3
    MAX_STOPS = 10

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="day_plans"
    )
    name = models.CharField(max_length=50)
    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_user_day_plan_name"
            )
        ]

    def __str__(self):
        return self.name


class DayPlanStop(models.Model):
    """One stop of a day plan. Every stop except the last has a leave time."""

    day_plan = models.ForeignKey(
        DayPlan, on_delete=models.CASCADE, related_name="stops"
    )
    zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="day_plan_stops"
    )
    position = models.PositiveSmallIntegerField()  # 0-based
    leave_time = models.TimeField(null=True, blank=True)  # null on the last stop

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["day_plan", "position"], name="unique_day_plan_stop_position"
            )
        ]

    def __str__(self):
        return f"{self.day_plan.name} #{self.position}"

    @property
    def leave_label(self):
        return self.leave_time.strftime("%H:%M") if self.leave_time else ""
