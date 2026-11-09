from django.db import models


class Zone(models.Model):
    """A NYC TLC taxi zone. Boundary shapes live in a GeoJSON file in
    zones/data/, keyed by zone_id, not in this table."""

    zone_id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    borough = models.CharField(max_length=50)

    class Meta:
        ordering = ["zone_id"]

    def __str__(self):
        return f"{self.zone_id} {self.name} ({self.borough})"


class ZoneHourStats(models.Model):
    """Precomputed trip stats for one zone, day of week, and hour.

    day_of_week follows Python's Monday=0 .. Sunday=6 convention.
    """

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name="hour_stats")
    day_of_week = models.PositiveSmallIntegerField()
    hour = models.PositiveSmallIntegerField()
    trip_count = models.PositiveIntegerField()
    avg_duration_min = models.FloatField()
    fare_min = models.DecimalField(max_digits=8, decimal_places=2)
    fare_avg = models.DecimalField(max_digits=8, decimal_places=2)
    fare_max = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["zone", "day_of_week", "hour"],
                name="unique_zone_hour_stats",
            )
        ]
        indexes = [
            models.Index(fields=["zone", "day_of_week", "hour"]),
        ]
        ordering = ["zone", "day_of_week", "hour"]

    def __str__(self):
        return f"zone={self.zone_id} day={self.day_of_week} hour={self.hour}"


class RouteHourStats(models.Model):
    """Precomputed trip stats for a pickup/dropoff zone pair, day of
    week, and hour.

    day_of_week follows Python's Monday=0 .. Sunday=6 convention.
    """

    pickup_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="routes_from"
    )
    dropoff_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="routes_to"
    )
    day_of_week = models.PositiveSmallIntegerField()
    hour = models.PositiveSmallIntegerField()
    trip_count = models.PositiveIntegerField()
    avg_duration_min = models.FloatField()
    fare_min = models.DecimalField(max_digits=8, decimal_places=2)
    fare_avg = models.DecimalField(max_digits=8, decimal_places=2)
    fare_max = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pickup_zone", "dropoff_zone", "day_of_week", "hour"],
                name="unique_route_hour_stats",
            )
        ]
        indexes = [
            models.Index(fields=["pickup_zone", "dropoff_zone", "day_of_week", "hour"]),
        ]
        ordering = ["pickup_zone", "dropoff_zone", "day_of_week", "hour"]

    def __str__(self):
        return (
            f"pickup={self.pickup_zone_id} dropoff={self.dropoff_zone_id} "
            f"day={self.day_of_week} hour={self.hour}"
        )


class RideshareStats(models.Model):
    """Statistics shared by the two rideshare (Uber and Lyft combined)
    tables. Units and rounding follow the taxi tables; see
    docs/decisions.md, "Rideshare import (US27 #74)".

    avg_wait_min averages only the wait_count trips with a wait from 0 to
    60 minutes, and is null when there are none. fare_per_mile is the
    cell's total fare over its total miles, null if the miles round to 0.
    """

    day_of_week = models.PositiveSmallIntegerField()
    hour = models.PositiveSmallIntegerField()
    trip_count = models.PositiveIntegerField()
    avg_duration_min = models.FloatField()
    fare_min = models.DecimalField(max_digits=8, decimal_places=2)
    fare_avg = models.DecimalField(max_digits=8, decimal_places=2)
    fare_max = models.DecimalField(max_digits=8, decimal_places=2)
    avg_wait_min = models.FloatField(null=True)
    wait_count = models.PositiveIntegerField()
    fare_per_mile = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    class Meta:
        abstract = True


class RideshareZoneHourStats(RideshareStats):
    """Rideshare stats for one pickup zone, day of week, and hour.

    day_of_week follows Python's Monday=0 .. Sunday=6 convention.
    """

    # db_index=False: the unique constraint's index already starts with it.
    zone = models.ForeignKey(
        Zone,
        on_delete=models.CASCADE,
        related_name="rideshare_hour_stats",
        db_index=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["zone", "day_of_week", "hour"],
                name="unique_rideshare_zone_hour_stats",
            )
        ]
        ordering = ["zone", "day_of_week", "hour"]

    def __str__(self):
        return f"zone={self.zone_id} day={self.day_of_week} hour={self.hour}"


class RideshareRouteHourStats(RideshareStats):
    """Rideshare stats for a pickup/dropoff zone pair, day of week, and
    hour.

    day_of_week follows Python's Monday=0 .. Sunday=6 convention.
    """

    # db_index=False: the unique constraint's index already starts with it.
    pickup_zone = models.ForeignKey(
        Zone,
        on_delete=models.CASCADE,
        related_name="rideshare_routes_from",
        db_index=False,
    )
    dropoff_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="rideshare_routes_to"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pickup_zone", "dropoff_zone", "day_of_week", "hour"],
                name="unique_rideshare_route_hour_stats",
            )
        ]
        ordering = ["pickup_zone", "dropoff_zone", "day_of_week", "hour"]

    def __str__(self):
        return (
            f"pickup={self.pickup_zone_id} dropoff={self.dropoff_zone_id} "
            f"day={self.day_of_week} hour={self.hour}"
        )
