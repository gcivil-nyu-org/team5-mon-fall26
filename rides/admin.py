from django.contrib import admin

from .models import RidePost


@admin.register(RidePost)
class RidePostAdmin(admin.ModelAdmin):
    """US31 #93: posts can be checked here until Epic 5 adds moderation."""

    list_display = (
        "departure_at",
        "owner",
        "pickup_zone",
        "dropoff_zone",
        "seats",
        "status",
        "created_at",
    )
    list_filter = ("status",)
    list_select_related = ("owner", "pickup_zone", "dropoff_zone")
    raw_id_fields = ("owner", "pickup_zone", "dropoff_zone")
    date_hierarchy = "departure_at"
