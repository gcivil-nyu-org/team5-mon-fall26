"""Reading the raw input files for the trip import."""

from pathlib import Path

import pandas as pd
import pyarrow
import pyarrow.parquet as pq

ZONE_LOOKUP_CSV = (
    Path(__file__).resolve().parent.parent / "data" / "taxi_zone_lookup.csv"
)

# The TLC columns the import needs, and our names for them. This is the
# only place that knows the raw names, so a renamed column is fixed here.
RAW_COLUMNS = {
    "tpep_pickup_datetime": "pickup_at",
    "tpep_dropoff_datetime": "dropoff_at",
    "PULocationID": "pickup_zone_id",
    "DOLocationID": "dropoff_zone_id",
    "payment_type": "payment_type",
    "trip_distance": "trip_distance",
    "fare_amount": "fare_amount",
    "tip_amount": "tip_amount",
    "total_amount": "total_amount",
}


class TripFileError(Exception):
    """A trip file cannot be read or is missing a column the import needs."""


def read_trips(path):
    """Read one monthly TLC trip file, keeping only RAW_COLUMNS, renamed."""
    try:
        names = pq.read_schema(path).names
    except (OSError, pyarrow.ArrowInvalid) as exc:
        raise TripFileError(f"Cannot read {path}: {exc}") from exc

    missing = [column for column in RAW_COLUMNS if column not in names]
    if missing:
        raise TripFileError(f"{path} is missing columns: {', '.join(missing)}")

    trips = pd.read_parquet(path, columns=list(RAW_COLUMNS))
    return trips.rename(columns=RAW_COLUMNS)


def read_zone_lookup(path=ZONE_LOOKUP_CSV):
    """Read the TLC taxi zone lookup as columns zone_id, name, borough.

    keep_default_na=False keeps the "N/A" text of zones 264 and 265
    instead of turning it into missing values.
    """
    lookup = pd.read_csv(
        path,
        usecols=["LocationID", "Zone", "Borough"],
        dtype={"LocationID": "int64"},
        keep_default_na=False,
    )
    lookup = lookup.rename(
        columns={"LocationID": "zone_id", "Zone": "name", "Borough": "borough"}
    )
    return lookup[["zone_id", "name", "borough"]]
