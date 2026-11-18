from django.contrib import admin
from django.utils.html import format_html, format_html_join

from zones.importer.clean import RULES as TAXI_RULES
from zones.importer.rideshare.clean import RULES as RIDESHARE_RULES

from .models import ImportRun, Zone

RULE_LABELS = {
    ImportRun.Dataset.TAXI: dict(TAXI_RULES),
    ImportRun.Dataset.RIDESHARE: dict(RIDESHARE_RULES),
}
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
        # In rule order (PostgreSQL's jsonb does not keep key order); a key
        # the code no longer has goes last, under its key.
        labels = RULE_LABELS[run.dataset]
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
