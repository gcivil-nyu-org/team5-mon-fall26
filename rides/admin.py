from django.contrib import admin
from django.db.models import Case, IntegerField, Value, When

from . import moderation
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
    """Only staff see reporters and perform moderation on reported content."""

    list_display = (
        "created_at",
        "reason",
        "status",
        "item_report_count",
        "kind",
        "reported_user",
        "reporter",
        "short_text",
    )
    list_filter = ("reason", "status")
    list_select_related = ("reporter", "post__owner", "message__sender")
    ordering = (
        Case(
            When(status=ContentReport.OPEN, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ).asc(),
        "-created_at",
        "-pk",
    )
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
        "status",
        "outcome",
        "closed_by",
        "closed_at",
    )
    fields = readonly_fields
    actions = ("remove_posts", "hide_messages", "no_action_needed")

    @admin.display(description="Reports on item")
    def item_report_count(self, report):
        return (
            report.post.reports.count()
            if report.post_id
            else report.message.reports.count()
        )

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

    def has_delete_permission(self, request, obj=None):
        return False  # keep report outcomes until the reported account is deleted

    @admin.action(description="Remove reported posts")
    def remove_posts(self, request, queryset):
        count = moderation.remove_posts(queryset, request.user)
        self.message_user(request, f"{count} post(s) removed.")

    @admin.action(description="Hide reported messages")
    def hide_messages(self, request, queryset):
        count = moderation.hide_messages(queryset, request.user)
        self.message_user(request, f"{count} message(s) hidden.")

    @admin.action(description="Close reports: no action needed")
    def no_action_needed(self, request, queryset):
        count = moderation.no_action(queryset, request.user)
        self.message_user(
            request, f"{count} report(s) closed without removing content."
        )
