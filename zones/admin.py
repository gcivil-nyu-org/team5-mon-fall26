from decimal import Decimal

from django.contrib import admin
from django.utils.html import format_html, format_html_join

from zones.importer import rules

from .models import CleaningRules, CleaningRulesChange, ImportRun, Zone

ERROR_START = 80


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """US39 #113: staff can list and view the rows but not add, change or
    delete them (also no "Delete selected" action). Used for zones and,
    in US40, the import history."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Zone)
class ZoneAdmin(ReadOnlyModelAdmin):
    """US39 #113: read-only for now; US42 makes the names editable."""

    list_display = ("zone_id", "name", "borough")
    list_filter = ("borough",)
    search_fields = ("name",)


@admin.register(ImportRun)
class ImportRunAdmin(ReadOnlyModelAdmin):
    """US40 #114: the import history, newest first. Read-only: runs are
    saved only by import_trips and import_rideshare."""

    list_display = (
        "started_at",
        "dataset",
        "months_text",
        "status",
        "run_by",
        "rows_read",
        "rows_kept",
        "zone_cells",
        "route_cells",
        "duration_text",
        "error_start",
    )
    list_filter = ("dataset", "status")
    list_display_links = ("started_at",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "dataset",
                    "months_text",
                    "status",
                    "run_by",
                    "started_at",
                    "finished_at",
                    "duration_text",
                    "error",
                )
            },
        ),
        (
            "Rows",
            {
                "fields": (
                    "rows_read",
                    "removed_table",
                    "rows_removed",
                    "rows_kept",
                    "waits_left_out",
                )
            },
        ),
        (
            "Cells written",
            {
                "fields": (
                    "zone_cells",
                    "small_zone_cells",
                    "route_cells",
                    "small_route_cells",
                    "min_trip_count",
                    "zones_loaded",
                )
            },
        ),
        ("Cleaning limits", {"fields": ("cleaning_limits",)}),
        ("Report as printed", {"fields": ("report_text",)}),
    )
    readonly_fields = (
        "months_text",
        "duration_text",
        "removed_table",
        "report_text",
    )

    @admin.display(description="Months")
    def months_text(self, run):
        return run.months_text

    @admin.display(description="Duration")
    def duration_text(self, run):
        if run.duration is None:
            return "-"
        minutes, seconds = divmod(round(run.duration.total_seconds()), 60)
        return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"

    @admin.display(description="Error")
    def error_start(self, run):
        if not run.error:
            return "-"
        if len(run.error) <= ERROR_START:
            return run.error
        return run.error[:ERROR_START] + "…"

    @admin.display(description="Rows removed by rule")
    def removed_table(self, run):
        if not run.removed_by_rule:
            return "-"
        # In rule order (PostgreSQL's jsonb does not keep key order), labelled
        # with the limits this run used (US41); a key the code no longer has
        # goes last, under its key.
        limits = rules.limits_from_saved(run.dataset, run.cleaning_limits)
        labels = dict(rules.rules_for(run.dataset, limits))
        removed = run.removed_by_rule
        keys = [key for key in labels if key in removed]
        keys += sorted(key for key in removed if key not in labels)
        rows = format_html_join(
            "",
            "<tr><td>{}</td><td>{}</td></tr>",
            ((labels.get(key, key), f"{removed[key]:,}") for key in keys),
        )
        return format_html("<table>{}</table>", rows)

    @admin.display(description="Report")
    def report_text(self, run):
        if not run.report:
            return "-"
        return format_html("<pre>{}</pre>", run.report)


LIMIT_FIELDS = ("max_fare", "min_distance_mi", "max_distance_mi")
DURATION_FIELDS = ("min_duration_min", "max_duration_min")
WAIT_FIELDS = ("min_wait_min", "max_wait_min")
CHANGE_FIELDS = LIMIT_FIELDS + DURATION_FIELDS + WAIT_FIELDS


@admin.register(CleaningRules)
class CleaningRulesAdmin(admin.ModelAdmin):
    """US41 #115: the cleaning limits, one record per import. Staff can
    change them, not add or delete a record. Each save that changes a
    limit is kept as a CleaningRulesChange (who, when, old and new), shown
    on the page. The next import uses the new limits."""

    list_display = (
        "dataset",
        "max_fare",
        "distance_text",
        "duration_text",
        "wait_text",
        "last_changed",
    )
    list_display_links = ("dataset",)
    readonly_fields = ("dataset", "last_changed", "change_history")

    def get_fieldsets(self, request, obj=None):
        fieldsets = [
            (None, {"fields": ("dataset",)}),
            ("Fare and distance", {"fields": LIMIT_FIELDS}),
            ("Duration", {"fields": DURATION_FIELDS}),
        ]
        if obj is not None and obj.is_rideshare:
            fieldsets.append(("Wait (rideshare only)", {"fields": WAIT_FIELDS}))
        fieldsets.append(
            (
                "Changes",
                {
                    "fields": ("last_changed", "change_history"),
                    "description": "The next import uses the limits saved "
                    "here; an import that is already running keeps the "
                    "limits it started with.",
                },
            )
        )
        return fieldsets

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Distance (miles)")
    def distance_text(self, record):
        return f"more than {record.min_distance_mi}, at most {record.max_distance_mi}"

    @admin.display(description="Duration (minutes)")
    def duration_text(self, record):
        return f"{record.min_duration_min} to {record.max_duration_min}"

    @admin.display(description="Wait (minutes)")
    def wait_text(self, record):
        if not record.is_rideshare:
            return "-"
        return f"{record.min_wait_min} to {record.max_wait_min}"

    @admin.display(description="Last changed")
    def last_changed(self, record):
        change = record.changes.first()
        if change is None:
            return "Never (starting values)"
        return f"{change.changed_at:%Y-%m-%d %H:%M} UTC by {change.changed_by}"

    @admin.display(description="History")
    def change_history(self, record):
        changes = record.changes.all()
        if not changes:
            return "No changes yet: these are the starting values."
        names = {name: CleaningRules._meta.get_field(name) for name in CHANGE_FIELDS}
        rows = format_html_join(
            "",
            "<tr><td>{}</td><td>{}</td><td>{}</td></tr>",
            (
                (
                    f"{change.changed_at:%Y-%m-%d %H:%M} UTC",
                    change.changed_by,
                    # In form order: PostgreSQL's jsonb does not keep key order.
                    "; ".join(
                        f"{names[name].verbose_name.capitalize()}: "
                        f"{change.changes[name][0]} → {change.changes[name][1]}"
                        for name in CHANGE_FIELDS
                        if name in change.changes
                    ),
                )
                for change in changes
            ),
        )
        return format_html(
            "<table><tr><th>When</th><th>Who</th><th>Changed</th></tr>{}</table>",
            rows,
        )

    def save_model(self, request, obj, form, change):
        """Save the limits and, if any changed, one change record. The admin
        runs both in one transaction."""
        before = CleaningRules.objects.get(pk=obj.pk)
        super().save_model(request, obj, form, change)
        changes = {
            name: [_text(getattr(before, name)), _text(getattr(obj, name))]
            for name in CHANGE_FIELDS
            if getattr(before, name) != getattr(obj, name)
        }
        if changes:
            CleaningRulesChange.objects.create(
                rules=obj, changed_by=request.user.get_username(), changes=changes
            )


def _text(value):
    """A limit as text for the change log. A wait limit is never empty
    here: taxi has none to change, and rideshare must have both."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)
