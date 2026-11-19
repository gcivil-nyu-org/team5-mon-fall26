from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.db.models import Case, IntegerField, Value, When
from django.utils.dateformat import format as format_date

from zones.views import NYC_TZ

from . import review
from .models import FareReport


class ReviewActionForm(ActionForm):
    """US44 #118: the optional reason box next to the "Action" menu."""

    reason = forms.CharField(
        required=False,
        max_length=200,
        label="Reason (optional)",
        widget=forms.TextInput(attrs={"size": 40}),
    )


@admin.register(FareReport)
class FareReportAdmin(admin.ModelAdmin):
    """US24 #71, US44 #118: held reports come first, each next to the
    route's usual fare for that day and hour. Staff select reports and
    choose "Approve" (visible to other riders) or "Remove" (hidden from
    every public view), with an optional reason; who and when are kept.
    The status can only change through these actions, and reports can't
    be added here (riders send them)."""

    action_form = ReviewActionForm
    actions = ("approve_reports", "remove_reports")
    list_display = (
        "created_at",
        "route",
        "ride_time",
        "taxi_fare",
        "usual_fare",
        "rideshare_service",
        "rideshare_quote",
        "status",
        "reviewed_by",
        "reviewed_at",
    )
    list_filter = ("status", "rideshare_service")
    list_select_related = ("user", "pickup_zone", "dropoff_zone")
    list_per_page = 25
    # Held reports first, then newest first.
    ordering = (
        Case(
            When(status=FareReport.HELD, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ).asc(),
        "-created_at",
        "-pk",
    )
    search_fields = ("pickup_zone__name", "dropoff_zone__name", "user__email")
    date_hierarchy = "created_at"
    fields = (
        "user",
        "pickup_zone",
        "dropoff_zone",
        "ride_at",
        "taxi_fare",
        "usual_fare",
        "rideshare_service",
        "rideshare_quote",
        "status",
        "created_at",
        "reviewed_by",
        "reviewed_at",
        "review_reason",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    @admin.display(description="route")
    def route(self, report):
        return f"{report.pickup_zone.name} → {report.dropoff_zone.name}"

    @admin.display(description="ride (New York time)", ordering="ride_at")
    def ride_time(self, report):
        return format_date(report.ride_at.astimezone(NYC_TZ), "D M j, Y, g:i A")

    @admin.display(description="usual fare (that day and hour)")
    def usual_fare(self, report):
        stats = review.usual_fare(report)
        if not stats["enough_data"]:
            return "Not enough data"
        return f"${stats['fare_avg']:.2f} ({stats['trip_count']:,} trips)"

    def _review(self, request, queryset, change, verb):
        reason = request.POST.get("reason", "")[:200]
        changed = change(queryset, request.user.get_username(), reason)
        unchanged = queryset.count() - changed
        message = f"{changed} report{'' if changed == 1 else 's'} {verb}."
        if unchanged:
            message += f" {unchanged} already {verb}, left as they were."
        self.message_user(request, message, messages.SUCCESS)

    @admin.action(description="Approve: show to other riders")
    def approve_reports(self, request, queryset):
        self._review(request, queryset, review.approve, "approved")

    @admin.action(description="Remove: hide from every public view")
    def remove_reports(self, request, queryset):
        self._review(request, queryset, review.remove, "removed")
