from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class Zone(models.Model):
    """A NYC TLC taxi zone. Boundary shapes live in a GeoJSON file in
    zones/data/, keyed by zone_id, not in this table.

    US42 #116: staff can correct the name and borough in the admin. Such a
    zone is marked edited_by_admin, and the imports leave its name and
    borough alone (zones/importer/load.py, upsert_zones)."""

    zone_id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    borough = models.CharField(max_length=50)
    # db_default as well as default, so code that does not know these
    # columns yet (an older checkout importing into the shared database)
    # can still insert zones.
    edited_by_admin = models.BooleanField(
        "edited in the admin",
        default=False,
        db_default=False,
        help_text="Ticked when staff change the name or borough here: the "
        "import then keeps this zone's name and borough. Untick it to let "
        "the next import put back the TLC name and borough.",
    )
    edited_by = models.CharField(
        "last edited by",
        max_length=150,
        blank=True,
        default="",
        db_default="",
        help_text="The staff member's email, kept even if the account is "
        "deleted later.",
    )
    edited_at = models.DateTimeField("last edited at", null=True, blank=True)

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
        help_text="The cleaning limits the import used, from the admin (US41)."
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


# US41 #115: the maximum fare can't be raised above the fare reports' limit
# (reports.models.MAX_FARE, US24), so a reported fare is always a fare the
# import could keep. reports imports zones, so the value is repeated here
# and a test checks that both are the same.
FARE_CAP = Decimal("500.00")

NEGATIVE = "Enter 0 or more: a limit cannot be negative."
FARE_NOT_POSITIVE = "The maximum fare must be more than $0."
FARE_OVER_CAP = (
    "The maximum fare can be at most $500, the highest fare a rider can "
    "report, so fare reports keep matching the statistics."
)
WAIT_REQUIRED = "Enter both wait limits for rideshare data."

# The limits before US41, which both records start with (migration
# zones/0006_cleaning_rules, and CleaningRules.current if a record is
# missing). Waits are rideshare only.
STARTING_VALUES = {
    "taxi": {
        "max_fare": Decimal("500.00"),
        "min_distance_mi": Decimal("0.00"),
        "max_distance_mi": Decimal("100.00"),
        "min_duration_min": 1,
        "max_duration_min": 180,
        "min_wait_min": None,
        "max_wait_min": None,
    },
    "rideshare": {
        "max_fare": Decimal("500.00"),
        "min_distance_mi": Decimal("0.00"),
        "max_distance_mi": Decimal("100.00"),
        "min_duration_min": 1,
        "max_duration_min": 180,
        "min_wait_min": 0,
        "max_wait_min": 60,
    },
}

# (minimum field, maximum field, message when the minimum is not below it)
MIN_MAX_PAIRS = (
    (
        "min_distance_mi",
        "max_distance_mi",
        "The maximum distance must be more than the minimum distance.",
    ),
    (
        "min_duration_min",
        "max_duration_min",
        "The maximum duration must be more than the minimum duration.",
    ),
    (
        "min_wait_min",
        "max_wait_min",
        "The maximum wait must be more than the minimum wait.",
    ),
)


class CleaningRules(models.Model):
    """US41 #115: the editable cleaning limits, one record per import
    (taxi, rideshare). Staff change them in the admin; the next import
    reads them when it starts (zones/importer/rules.py). Every change is
    kept in CleaningRulesChange. See docs/decisions.md (US41)."""

    dataset = models.CharField(
        max_length=20, choices=ImportRun.Dataset.choices, unique=True
    )
    max_fare = models.DecimalField(
        "maximum fare ($)",
        max_digits=6,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.01"), FARE_NOT_POSITIVE),
            MaxValueValidator(FARE_CAP, FARE_OVER_CAP),
        ],
        help_text="A trip whose fare before tip is above this is removed. "
        "At most $500.",
    )
    min_distance_mi = models.DecimalField(
        "minimum distance (miles)",
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(0, NEGATIVE)],
        help_text="A trip of this distance or less is removed (0 removes "
        "only zero-mile trips).",
    )
    max_distance_mi = models.DecimalField(
        "maximum distance (miles)",
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(0, NEGATIVE)],
        help_text="A trip longer than this is removed.",
    )
    min_duration_min = models.IntegerField(
        "minimum duration (minutes)",
        validators=[MinValueValidator(0, NEGATIVE)],
        help_text="A trip shorter than this is removed.",
    )
    max_duration_min = models.IntegerField(
        "maximum duration (minutes)",
        validators=[MinValueValidator(0, NEGATIVE)],
        help_text="A trip longer than this is removed.",
    )
    min_wait_min = models.IntegerField(
        "minimum wait (minutes)",
        null=True,
        blank=True,
        validators=[MinValueValidator(0, NEGATIVE)],
        help_text="Rideshare only. A wait below this is left out of the wait "
        "average; the trip is kept.",
    )
    max_wait_min = models.IntegerField(
        "maximum wait (minutes)",
        null=True,
        blank=True,
        validators=[MinValueValidator(0, NEGATIVE)],
        help_text="Rideshare only. A wait above this is left out of the wait "
        "average; the trip is kept.",
    )

    class Meta:
        ordering = ["dataset"]
        verbose_name = "cleaning rules"
        verbose_name_plural = "cleaning rules"
        constraints = [
            models.CheckConstraint(
                condition=Q(max_fare__gt=0, max_fare__lte=FARE_CAP),
                name="cleaningrules_fare_in_range",
            ),
            models.CheckConstraint(
                condition=Q(
                    min_distance_mi__gte=0,
                    max_distance_mi__gt=F("min_distance_mi"),
                ),
                name="cleaningrules_distance_in_order",
            ),
            models.CheckConstraint(
                condition=Q(
                    min_duration_min__gte=0,
                    max_duration_min__gt=F("min_duration_min"),
                ),
                name="cleaningrules_duration_in_order",
            ),
            models.CheckConstraint(
                condition=Q(
                    dataset="taxi", min_wait_min__isnull=True, max_wait_min__isnull=True
                )
                | Q(
                    dataset="rideshare",
                    min_wait_min__isnull=False,
                    max_wait_min__isnull=False,
                    min_wait_min__gte=0,
                    max_wait_min__gt=F("min_wait_min"),
                ),
                name="cleaningrules_wait_rideshare_only",
            ),
        ]

    def __str__(self):
        return f"{self.get_dataset_display()} cleaning rules"

    @property
    def is_rideshare(self):
        return self.dataset == ImportRun.Dataset.RIDESHARE

    def clean(self):
        if not self.is_rideshare:
            self.min_wait_min = self.max_wait_min = None
        elif self.min_wait_min is None or self.max_wait_min is None:
            missing = [
                name
                for name in ("min_wait_min", "max_wait_min")
                if getattr(self, name) is None
            ]
            raise ValidationError({name: WAIT_REQUIRED for name in missing})

        errors = {}
        for low_name, high_name, message in MIN_MAX_PAIRS:
            low, high = getattr(self, low_name), getattr(self, high_name)
            if low is not None and high is not None and not low < high:
                errors[high_name] = message
        if errors:
            raise ValidationError(errors)

    @classmethod
    def current(cls, dataset):
        """The record for an import, made with the starting values if it
        is missing (the migration makes both)."""
        rules, _ = cls.objects.get_or_create(
            dataset=dataset, defaults=STARTING_VALUES[dataset]
        )
        return rules


class CleaningRulesChange(models.Model):
    """US41 #115: one change to a CleaningRules record, made in the admin:
    who (their email, kept even if the account is deleted later), when,
    and each changed limit's old and new value."""

    rules = models.ForeignKey(
        CleaningRules, on_delete=models.CASCADE, related_name="changes"
    )
    changed_by = models.CharField(max_length=150)
    changed_at = models.DateTimeField(default=timezone.now)
    changes = models.JSONField(
        help_text='Field name to [old, new], as text, e.g. {"max_fare": '
        '["500.00", "450.00"]}.'
    )

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.rules} changed by {self.changed_by} at {self.changed_at}"


class ZoneAdjacencyOverride(models.Model):
    """US43 #117: staff add a pair of neighbouring zones that
    zone_neighbors.json (US18) misses, or remove a wrong one, with a reason.

    The pair is stored once, lower zone id first, and always applies both
    ways. zones.stats.load_zone_neighbors() combines the file with these
    rows, so cheaper-pickup suggestions (US19) and ride matching (US32) use
    the result straight away. Deleting a row puts the pair back to what the
    file says. The rows live in the database, so rebuilding the file with
    scripts/build_zone_neighbors.py keeps them."""

    ADD = "add"
    REMOVE = "remove"
    ACTION_CHOICES = [
        (ADD, "Add: make them neighbours"),
        (REMOVE, "Remove: they are not neighbours"),
    ]

    zone_a = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="+", verbose_name="zone"
    )
    zone_b = models.ForeignKey(
        Zone,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name="other zone",
    )
    action = models.CharField(max_length=6, choices=ACTION_CHOICES)
    reason = models.CharField(
        max_length=200,
        help_text="Why the file is wrong for this pair, for example "
        '"Joined by a bridge" or "Separated by the river".',
    )
    changed_by = models.CharField(
        "last changed by",
        max_length=150,
        blank=True,
        default="",
        help_text="The staff member's email, kept even if the account is "
        "deleted later.",
    )
    changed_at = models.DateTimeField("last changed at", default=timezone.now)

    class Meta:
        ordering = ["zone_a", "zone_b"]
        verbose_name = "neighbour override"
        constraints = [
            models.UniqueConstraint(
                fields=["zone_a", "zone_b"],
                name="unique_adjacency_override_pair",
                violation_error_message="This pair already has an override. "
                "Change or delete that one instead.",
            ),
            models.CheckConstraint(
                condition=Q(zone_a__lt=F("zone_b")),
                name="adjacency_override_lower_zone_first",
            ),
        ]

    def __str__(self):
        verb = "add" if self.action == self.ADD else "remove"
        return f"{verb} {self.zone_a_id} ↔ {self.zone_b_id}"

    def _put_lower_zone_first(self):
        if (
            self.zone_a_id is not None
            and self.zone_b_id is not None
            and self.zone_a_id > self.zone_b_id
        ):
            self.zone_a_id, self.zone_b_id = self.zone_b_id, self.zone_a_id

    def clean(self):
        """A zone can't be paired with itself; "add" must be a pair the file
        doesn't already have, and "remove" one it does."""
        if self.zone_a_id is None or self.zone_b_id is None:
            return
        if self.zone_a_id == self.zone_b_id:
            raise ValidationError(
                {"zone_b": "A zone can't be its own neighbour. Pick two zones."}
            )
        self._put_lower_zone_first()
        from .stats import file_zone_neighbors

        in_file = self.zone_b_id in file_zone_neighbors().get(self.zone_a_id, [])
        if self.action == self.ADD and in_file:
            raise ValidationError(
                {
                    "action": "These zones are already neighbours in "
                    "zone_neighbors.json, so there is nothing to add."
                }
            )
        if self.action == self.REMOVE and not in_file:
            raise ValidationError(
                {
                    "action": "These zones aren't neighbours in "
                    "zone_neighbors.json, so there is nothing to remove."
                }
            )

    def save(self, *args, **kwargs):
        self._put_lower_zone_first()
        super().save(*args, **kwargs)
