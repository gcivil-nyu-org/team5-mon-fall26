"""The whole import: one month at a time, then one database transaction."""

from dataclasses import dataclass
from urllib.error import URLError

import pandas as pd

from zones.importer.aggregate import (
    ROUTE_KEYS,
    ZONE_KEYS,
    combine_partials,
    finalize,
    partial_totals,
)
from zones.importer.clean import clean_trips
from zones.importer.download import TRIP_URL, ensure_trip_file, trip_file_path
from zones.importer.load import load_all
from zones.importer.read import TripFileError, read_trips, read_zone_lookup
from zones.importer.report import MonthReport


@dataclass
class ImportResult:
    months: list
    zone_stats: pd.DataFrame
    route_stats: pd.DataFrame
    zones_loaded: int


def _trip_file(month, data_dir, progress):
    if not trip_file_path(month, data_dir).exists():
        progress(f"{month}: downloading {TRIP_URL.format(month=month)}")
    try:
        path, _ = ensure_trip_file(month, data_dir)
    except (URLError, OSError) as exc:
        raise TripFileError(f"Could not download {month}: {exc}") from exc
    return path


def run_import(months, data_dir, progress=lambda message: None):
    """Import the given months and replace all statistics with them.

    Only one month of raw trips is in memory at a time: each month is
    reduced to partial totals per cell before the next one is read.
    """
    lookup = read_zone_lookup()
    known_zone_ids = set(lookup["zone_id"])
    reports = []
    zone_acc = route_acc = None

    for month in months:
        trips = read_trips(_trip_file(month, data_dir, progress))
        kept, removed = clean_trips(trips, month, known_zone_ids)
        reports.append(MonthReport(month, len(trips), removed, len(kept)))
        del trips

        zone_acc = combine_partials(zone_acc, partial_totals(kept, ZONE_KEYS))
        route_acc = combine_partials(route_acc, partial_totals(kept, ROUTE_KEYS))
        progress(f"{month}: {reports[-1].rows_read:,} read, {reports[-1].rows_kept:,} kept")
        del kept

    zone_stats = finalize(zone_acc)
    route_stats = finalize(route_acc)
    progress(f"Writing {len(zone_stats):,} zone cells and {len(route_stats):,} route cells")
    zones_loaded, _, _ = load_all(lookup, zone_stats, route_stats)
    return ImportResult(reports, zone_stats, route_stats, zones_loaded)
