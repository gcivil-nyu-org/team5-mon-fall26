"""The whole rideshare import: download, then every month in batches,
then one database transaction."""

from dataclasses import dataclass
from urllib.error import URLError

import pandas as pd

from zones.importer.read import TripFileError, read_zone_lookup
from zones.importer.report import MonthReport
from zones.importer.rideshare.aggregate import Totals
from zones.importer.rideshare.clean import add_removed, clean_trips
from zones.importer.rideshare.download import (
    RIDESHARE_URL,
    ensure_rideshare_file,
    rideshare_file_path,
)
from zones.importer.rideshare.load import load_rideshare
from zones.importer.rideshare.read import read_batches


@dataclass
class RideshareImportResult:
    months: list
    zone_stats: pd.DataFrame
    route_stats: pd.DataFrame
    zones_loaded: int


def _rideshare_file(month, data_dir, progress):
    if not rideshare_file_path(month, data_dir).exists():
        progress(f"{month}: downloading {RIDESHARE_URL.format(month=month)}")
    try:
        path, _ = ensure_rideshare_file(month, data_dir)
    except (URLError, OSError) as exc:
        raise TripFileError(f"Could not download {month}: {exc}") from exc
    return path


def _import_month(month, batches, known_zone_ids, totals):
    """Clean every batch of one month into totals. Returns its report."""
    rows_read = rows_kept = waits_left_out = 0
    removed = add_removed()
    for trips in batches:
        kept, batch_removed = clean_trips(trips, month, known_zone_ids)
        rows_read += len(trips)
        rows_kept += len(kept)
        waits_left_out += int((~kept["wait_valid"]).sum())
        removed = add_removed(removed, batch_removed)
        totals.add(kept)
    return MonthReport(month, rows_read, removed, rows_kept, waits_left_out)


def run_rideshare_import(months, data_dir, progress=lambda message: None):
    """Import the given months and replace both rideshare tables with them.

    Every file is downloaded if missing and checked before any trip is
    read, so a missing month or a bad file fails before the long part.
    Trips are read a batch at a time; only the running totals per cell
    are kept across batches and months.
    """
    lookup = read_zone_lookup()
    known_zone_ids = set(lookup["zone_id"])
    paths = [_rideshare_file(month, data_dir, progress) for month in months]
    batches = [read_batches(path) for path in paths]

    totals = Totals()
    reports = []
    for month, month_batches in zip(months, batches):
        report = _import_month(month, month_batches, known_zone_ids, totals)
        reports.append(report)
        progress(f"{month}: {report.rows_read:,} read, {report.rows_kept:,} kept")

    zone_stats, route_stats = totals.stats()
    progress(
        f"Writing {len(zone_stats):,} zone cells and {len(route_stats):,} route cells"
    )
    zones_loaded, _, _ = load_rideshare(lookup, zone_stats, route_stats)
    return RideshareImportResult(reports, zone_stats, route_stats, zones_loaded)
