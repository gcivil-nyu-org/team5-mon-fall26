"""US48 #122: the data-quality dashboard. Staff only, linked from the admin
home. For the taxi and rideshare imports: the latest successful import's
rows kept and removed by each cleaning rule, the share of cells below
MIN_TRIP_COUNT and the zones with no trips, compared with the import before
it; plus the fare reports held for review and the open content reports."""

from dataclasses import dataclass, field

from django.contrib import admin
from django.shortcuts import render
from django.urls import reverse

from reports.models import FareReport
from rides.models import ContentReport
from zones.importer import rules

from .models import ImportRun, RideshareZoneHourStats, Zone, ZoneHourStats

# A rule whose share of removed rows changed by more than this many
# percentage points since the previous import is highlighted.
CHANGE_LIMIT_PP = 2.0

ZONE_STATS = {
    ImportRun.Dataset.TAXI: ZoneHourStats,
    ImportRun.Dataset.RIDESHARE: RideshareZoneHourStats,
}


def share(part, whole):
    """part as a percentage of whole, or None if there is nothing to divide."""
    if part is None or not whole:
        return None
    return 100 * part / whole


@dataclass
class RuleRow:
    key: str
    label: str
    removed: int | None
    share: float | None
    previous_share: float | None

    @property
    def change(self):
        if self.share is None or self.previous_share is None:
            return None
        return self.share - self.previous_share

    @property
    def flagged(self):
        # Rounded so float noise never turns exactly 2 points into "more than".
        change = self.change
        return change is not None and round(abs(change), 9) > CHANGE_LIMIT_PP


@dataclass
class DatasetSummary:
    dataset: str
    label: str
    latest: ImportRun | None = None
    previous: ImportRun | None = None
    last_attempt: ImportRun | None = None
    rules: list = field(default_factory=list)
    zones_without_trips: list = field(default_factory=list)

    @property
    def last_attempt_failed(self):
        """The newest run is not the latest successful one (failed or running)."""
        return self.last_attempt is not None and self.last_attempt != self.latest

    @property
    def kept_share(self):
        return share(self.latest.rows_kept, self.latest.rows_read)

    @property
    def removed_share(self):
        return share(self.latest.rows_removed, self.latest.rows_read)

    @property
    def previous_removed_share(self):
        if self.previous is None:
            return None
        return share(self.previous.rows_removed, self.previous.rows_read)

    @property
    def small_cell_share(self):
        return small_cell_share(self.latest)

    @property
    def previous_small_cell_share(self):
        return small_cell_share(self.previous) if self.previous else None

    @property
    def small_zone_share(self):
        return share(self.latest.small_zone_cells, self.latest.zone_cells)

    @property
    def small_route_share(self):
        return share(self.latest.small_route_cells, self.latest.route_cells)

    @property
    def flagged_count(self):
        return sum(row.flagged for row in self.rules)


def small_cell_share(run):
    """Zone and route cells together, as in the import report."""
    cells = (run.zone_cells or 0) + (run.route_cells or 0)
    small = (run.small_zone_cells or 0) + (run.small_route_cells or 0)
    return share(small, cells)


def rule_rows(latest, previous):
    """One row per cleaning rule, in rule order, labelled with the limits the
    latest import used. A rule missing from one of the runs (added or
    removed in between) has no comparison."""
    limits = rules.limits_from_saved(latest.dataset, latest.cleaning_limits)
    labels = dict(rules.rules_for(latest.dataset, limits))
    removed = latest.removed_by_rule or {}
    before = (previous.removed_by_rule or {}) if previous else {}
    keys = [key for key in labels if key in removed or key in before]
    keys += sorted((set(removed) | set(before)) - set(labels))
    return [
        RuleRow(
            key=key,
            label=labels.get(key, key),
            removed=removed.get(key),
            share=share(removed.get(key), latest.rows_read),
            previous_share=(
                share(before[key], previous.rows_read)
                if previous is not None and key in before
                else None
            ),
        )
        for key in keys
    ]


def zones_without_trips(dataset):
    """Zones with no row in the dataset's zone statistics, which the latest
    successful import wrote (each import replaces them)."""
    stats = ZONE_STATS[dataset].objects.values("zone_id")
    return list(Zone.objects.exclude(zone_id__in=stats).order_by("zone_id"))


def summary(dataset):
    runs = ImportRun.objects.filter(dataset=dataset)
    done = list(
        runs.filter(status=ImportRun.Status.SUCCEEDED).order_by("-started_at", "-id")[
            :2
        ]
    )
    result = DatasetSummary(
        dataset=dataset,
        label=ImportRun.Dataset(dataset).label,
        latest=done[0] if done else None,
        previous=done[1] if len(done) > 1 else None,
        last_attempt=runs.order_by("-started_at", "-id").first(),
    )
    if result.latest is not None:
        result.rules = rule_rows(result.latest, result.previous)
        result.zones_without_trips = zones_without_trips(dataset)
    return result


def review_counts():
    """The held fare reports and open content reports, each with the link
    to its filtered admin list."""
    return [
        {
            "label": "Fare reports held for review",
            "count": FareReport.objects.filter(status=FareReport.HELD).count(),
            "url": reverse("admin:reports_farereport_changelist")
            + f"?status__exact={FareReport.HELD}",
        },
        {
            "label": "Open content reports",
            "count": ContentReport.objects.filter(status=ContentReport.OPEN).count(),
            "url": reverse("admin:rides_contentreport_changelist")
            + f"?status__exact={ContentReport.OPEN}",
        },
    ]


def data_quality(request):
    """The dashboard page. Wrapped in admin.site.admin_view in the URLs, so
    only active staff reach it (others go to the admin sign-in)."""
    context = {
        **admin.site.each_context(request),
        "title": "Data quality",
        "datasets": [summary(dataset) for dataset in ImportRun.Dataset.values],
        "review_counts": review_counts(),
        "change_limit_pp": CHANGE_LIMIT_PP,
    }
    return render(request, "admin/zones/data_quality.html", context)
