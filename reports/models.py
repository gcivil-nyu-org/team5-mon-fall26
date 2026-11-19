from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from zones.models import Zone

MAX_FARE = Decimal("500.00")


class FareReportQuerySet(models.QuerySet):
    def public(self):
        """Reports other riders may see: held and removed reports stay out."""
        return self.filter(status=FareReport.VISIBLE)


class FareReport(models.Model):
    """US24 #71: what a rider paid for a taxi ride, and optionally the Uber
    or Lyft price quoted at the same time. Zones only, never addresses."""

    VISIBLE = "visible"
    HELD = "held"
    REMOVED = "removed"  # US44 #118: by a staff member, after review
    STATUS_CHOICES = [
        (VISIBLE, "Visible"),
        (HELD, "Held for review"),
        (REMOVED, "Removed by a moderator"),
    ]
    SERVICE_CHOICES = [("uber", "Uber"), ("lyft", "Lyft")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fare_reports",
    )
    pickup_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="fare_reports_from"
    )
    dropoff_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="fare_reports_to"
    )
    ride_at = models.DateTimeField()
    taxi_fare = models.DecimalField(max_digits=6, decimal_places=2)
    rideshare_service = models.CharField(
        max_length=4, choices=SERVICE_CHOICES, blank=True
    )
    rideshare_quote = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(
        max_length=7, choices=STATUS_CHOICES, default=VISIBLE, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # US44 #118: the last approval or removal. db_default as well as
    # default, so code that doesn't know these columns yet (Production,
    # which shares the database with Integration) can still save reports.
    reviewed_by = models.CharField(
        max_length=150,
        blank=True,
        default="",
        db_default="",
        help_text="The staff member's email, kept even if the account is "
        "deleted later.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(
        max_length=200, blank=True, default="", db_default=""
    )

    objects = FareReportQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(taxi_fare__gt=0, taxi_fare__lte=MAX_FARE),
                name="fare_report_taxi_fare_range",
            ),
            models.CheckConstraint(
                condition=Q(rideshare_quote__isnull=True)
                | Q(rideshare_quote__gt=0, rideshare_quote__lte=MAX_FARE),
                name="fare_report_quote_range",
            ),
            # A quote needs a service, and the other way round.
            models.CheckConstraint(
                condition=Q(rideshare_service="", rideshare_quote__isnull=True)
                | (~Q(rideshare_service="") & Q(rideshare_quote__isnull=False)),
                name="fare_report_quote_with_service",
            ),
        ]

    def __str__(self):
        return (
            f"{self.pickup_zone.name} → {self.dropoff_zone.name}, "
            f"${self.taxi_fare} ({self.get_status_display()})"
        )
