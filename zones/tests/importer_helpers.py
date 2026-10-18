"""Small trip DataFrames and Parquet files for the importer tests."""

import pandas as pd

from zones.importer.read import RAW_COLUMNS

# One valid March 2026 trip (Tuesday 08:00), in our column names.
VALID_TRIP = {
    "pickup_at": "2026-03-10 08:00:00",
    "dropoff_at": "2026-03-10 08:15:00",
    "pickup_zone_id": 161,
    "dropoff_zone_id": 237,
    "payment_type": 1,
    "trip_distance": 2.5,
    "fare_amount": 15.0,
    "tip_amount": 3.0,
    "total_amount": 22.5,
}

# Every zone in the lookup CSV, as the pipeline passes them to clean_trips.
KNOWN_ZONE_IDS = set(range(1, 266))


def make_trips(*overrides):
    """One trip per override dict, each starting from VALID_TRIP.

    The result looks like read_trips() output: datetime64[us] times, and
    a zone column with a missing value becomes float64, as in real files.
    """
    trips = pd.DataFrame([{**VALID_TRIP, **row} for row in overrides])
    for column in ("pickup_at", "dropoff_at"):
        trips[column] = pd.to_datetime(trips[column]).astype("datetime64[us]")
    return trips


def make_kept(*rows):
    """Cleaned trips as clean_trips() returns them. Each row is
    (pickup, dropoff, day_of_week, hour, duration_s, fare_cents)."""
    kept = pd.DataFrame(
        rows,
        columns=[
            "pickup_zone_id",
            "dropoff_zone_id",
            "day_of_week",
            "hour",
            "duration_s",
            "fare_cents",
        ],
    )
    return kept.astype(
        {
            "pickup_zone_id": "int16",
            "dropoff_zone_id": "int16",
            "day_of_week": "int8",
            "hour": "int8",
            "duration_s": "int64",
            "fare_cents": "int64",
        }
    )


def write_parquet(trips, path, extra_columns=None):
    """Write trips to a Parquet file with the raw TLC column names."""
    ours_to_raw = {ours: raw for raw, ours in RAW_COLUMNS.items()}
    raw = trips.rename(columns=ours_to_raw)
    for name, value in (extra_columns or {}).items():
        raw[name] = value
    raw.to_parquet(path, index=False)
