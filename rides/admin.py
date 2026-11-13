from django.contrib import admin

from .models import RideInterest, RidePost


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


@admin.register(RideInterest)
class RideInterestAdmin(admin.ModelAdmin):
    """US33 #95: interest in a post, checked here until Epic 5."""

    list_display = ("post", "rider", "status", "created_at")
    list_filter = ("status",)
    list_select_related = ("post__pickup_zone", "post__dropoff_zone", "rider")
    raw_id_fields = ("post", "rider")
