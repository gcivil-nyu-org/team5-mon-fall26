from decimal import Decimal

from django import forms
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from zones.importer import rules

from .models import (
    CleaningRules,
    CleaningRulesChange,
    ImportRun,
    Zone,
    ZoneAdjacencyOverride,
)
from .stats import neighbor_sources

ERROR_START = 80


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """US39 #113: staff can list and view the rows but not add, change or
    delete them (also no "Delete selected" action). Used for the import
    history (US40); zones were read-only until US42."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# The boroughs in the TLC zone lookup (zones/data/taxi_zone_lookup.csv). A
# zone's borough is picked from these, so a typo can't make a new borough.
BOROUGHS = (
    "Bronx",
    "Brooklyn",
    "EWR",
    "Manhattan",
    "Queens",
    "Staten Island",
    "Unknown",
    "N/A",
)


class ZoneForm(forms.ModelForm):
    borough = forms.ChoiceField(choices=[(name, name) for name in BOROUGHS])

    class Meta:
        model = Zone
        fields = ("name", "borough", "edited_by_admin")

    def clean_name(self):
        """Inner runs of spaces become one. Django has already trimmed the
        name and refused a blank one ("This field is required.")."""
        return " ".join(self.cleaned_data["name"].split())


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    """US42 #116: staff correct a zone's name and borough; the zone id stays
    as it is, and zones can't be added or deleted (deleting would delete
    their statistics, plans and posts). A zone whose name or borough is
    changed here is marked edited_by_admin, with who and when, and the
    imports then leave it alone (zones/importer/load.py)."""

    form = ZoneForm
    list_display = (
        "zone_id",
        "name",
        "borough",
        "edited_by_admin",
        "edited_by",
        "edited_at",
    )
    list_filter = ("borough", "edited_by_admin")
    search_fields = ("name",)
    fields = (
        "zone_id",
        "name",
        "borough",
        "edited_by_admin",
        "edited_by",
        "edited_at",
        "neighbours",
    )
    readonly_fields = ("zone_id", "edited_by", "edited_at", "neighbours")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="neighbours")
    def neighbours(self, zone):
        """US43 #117: the zone's neighbours, each marked as coming from
        zone_neighbors.json, added in the admin, or removed in the admin
        (shown struck through: no longer used)."""
        sources = neighbor_sources(zone.zone_id)
        if not sources:
            return "None"
        names = dict(
            Zone.objects.filter(
                zone_id__in=[other for other, _ in sources]
            ).values_list("zone_id", "name")
        )
        labels = {
            "file": "from the file",
            "added": "added in the admin",
            "removed": "removed in the admin",
        }
        items = []
        for other, source in sources:
            tag = "s" if source == "removed" else "span"
            name = names.get(other, "Unknown zone")
            items.append((tag, other, name, tag, labels[source]))
        return format_html(
            '<ul style="margin:0;padding-left:1.2em">{}</ul>',
            format_html_join("", "<li><{}>{} {}</{}> ({})</li>", items),
        )

    def save_model(self, request, obj, form, change):
        """A changed name or borough marks the zone as edited. Any change
        (including unticking "edited in the admin") records who and when."""
        before = Zone.objects.get(pk=obj.pk)
        renamed = (obj.name, obj.borough) != (before.name, before.borough)
        if renamed:
            obj.edited_by_admin = True
        if renamed or obj.edited_by_admin != before.edited_by_admin:
            obj.edited_by = request.user.get_username()
            obj.edited_at = timezone.now()
        super().save_model(request, obj, form, change)


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


@admin.register(ZoneAdjacencyOverride)
class ZoneAdjacencyOverrideAdmin(admin.ModelAdmin):
    """US43 #117: add a pair of neighbouring zones that zone_neighbors.json
    misses, or remove a wrong one, with a reason. Applies both ways and
    straight away (zones.stats.load_zone_neighbors). Deleting an override
    puts the pair back to what the file says."""

    list_display = (
        "__str__",
        "zone_a",
        "zone_b",
        "action",
        "reason",
        "changed_by",
        "changed_at",
    )
    list_filter = ("action",)
    search_fields = ("zone_a__name", "zone_b__name", "reason")
    autocomplete_fields = ("zone_a", "zone_b")
    fields = ("zone_a", "zone_b", "action", "reason", "changed_by", "changed_at")
    readonly_fields = ("changed_by", "changed_at")

    def save_model(self, request, obj, form, change):
        obj.changed_by = request.user.get_username()
        obj.changed_at = timezone.now()
        super().save_model(request, obj, form, change)
