from django.contrib import admin

from .models import ContentReport, RideInterest, RidePost


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


@admin.register(ContentReport)
class ContentReportAdmin(admin.ModelAdmin):
    """US38 #101: reports are checked here until Epic 5 adds moderation.
    Only admins see who reported what."""

    list_display = (
        "created_at",
        "reason",
        "status",
        "kind",
        "reported_user",
        "reporter",
        "short_text",
    )
    list_filter = ("reason", "status")
    list_select_related = ("reporter", "post__owner", "message__sender")
    readonly_fields = (
        "reporter",
        "post",
        "message",
        "kind",
        "reported_user",
        "reported_text",
        "current_content",
        "reason",
        "note",
        "created_at",
    )
    fields = readonly_fields + ("status",)
    actions = ("mark_closed", "mark_open")

    @admin.display(description="Reported content (when reported)")
    def short_text(self, report):
        text = report.reported_text
        return text if len(text) <= 140 else f"{text[:137]}..."

    @admin.display(description="Content now")
    def current_content(self, report):
        if report.message_id:
            return report.message.text
        post = report.post
        return f"{post} Note: {post.note or '(none)'}"

    def has_add_permission(self, request):
        return False  # reports come from riders, not from the admin

    @admin.action(description="Mark selected reports closed")
    def mark_closed(self, request, queryset):
        queryset.update(status=ContentReport.CLOSED)

    @admin.action(description="Mark selected reports open")
    def mark_open(self, request, queryset):
        queryset.update(status=ContentReport.OPEN)
