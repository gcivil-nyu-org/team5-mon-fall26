from django.contrib import admin

from .models import FareReport


@admin.register(FareReport)
class FareReportAdmin(admin.ModelAdmin):
    """US24 #71: held reports can be checked here until Epic 5 adds review."""

    list_display = (
        "created_at",
        "user",
        "pickup_zone",
        "dropoff_zone",
        "ride_at",
        "taxi_fare",
        "rideshare_service",
        "rideshare_quote",
        "status",
    )
    list_filter = ("status", "rideshare_service")
    list_select_related = ("user", "pickup_zone", "dropoff_zone")
    raw_id_fields = ("user", "pickup_zone", "dropoff_zone")
    date_hierarchy = "created_at"
