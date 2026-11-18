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


class ImportRun(models.Model):
    """US40 #114: one run of import_trips or import_rideshare.

    Saved as "running" when the import starts, outside the import's own
    transaction, then filled in with the report's numbers when it
    succeeds, or marked "failed" with the error. The counts stay empty for
    a failed run, which prints no report. See docs/decisions.md (US40).
    """

    class Dataset(models.TextChoices):
        TAXI = "taxi", "Yellow taxi"
        RIDESHARE = "rideshare", "Rideshare (Uber and Lyft)"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    dataset = models.CharField(max_length=20, choices=Dataset.choices)
    months = models.JSONField(help_text='The months given, e.g. ["2026-03"].')
    run_by = models.CharField(
        max_length=150,
        help_text="The --by value, or the operating-system user who ran it.",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RUNNING
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    # Totals over all months, as in the report's "Total" block.
    rows_read = models.PositiveBigIntegerField(null=True, blank=True)
    removed_by_rule = models.JSONField(
        null=True, blank=True, help_text="Rows removed per cleaning rule key."
    )
    rows_removed = models.PositiveBigIntegerField(null=True, blank=True)
    rows_kept = models.PositiveBigIntegerField(null=True, blank=True)
    waits_left_out = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="Rideshare only."
    )

    # Cells written to the zone and route statistics tables.
    zone_cells = models.PositiveIntegerField(null=True, blank=True)
    route_cells = models.PositiveIntegerField(null=True, blank=True)
    small_zone_cells = models.PositiveIntegerField(null=True, blank=True)
    small_route_cells = models.PositiveIntegerField(null=True, blank=True)
    min_trip_count = models.PositiveSmallIntegerField(
        help_text="MIN_TRIP_COUNT when the import ran (the small-cell limit)."
    )
    zones_loaded = models.PositiveIntegerField(null=True, blank=True)

    cleaning_limits = models.JSONField(
        help_text="The cleaning limits in the code when the import ran."
    )
    report = models.TextField(blank=True, help_text="The report as printed.")
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        verbose_name = "import run"
        verbose_name_plural = "import history"

    def __str__(self):
        return (
            f"{self.get_dataset_display()} {self.months_text} "
            f"({self.get_status_display()}) #{self.pk}"
        )

    @property
    def months_text(self):
        return ", ".join(self.months)

    @property
    def duration(self):
        if self.finished_at is None:
            return None
        return self.finished_at - self.started_at
