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
