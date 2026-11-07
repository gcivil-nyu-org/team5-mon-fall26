"""Small High Volume FHV tables and Parquet files for the rideshare importer
tests, with the raw TLC column names and types."""

from datetime import datetime

import pyarrow as pa
import pyarrow.parquet as pq

from zones.importer.rideshare.read import to_frame

# Every column of the real files, with the types of the March 2026 file.
RAW_SCHEMA = pa.schema(
    [
        ("hvfhs_license_num", pa.large_string()),
        ("dispatching_base_num", pa.large_string()),
        ("originating_base_num", pa.large_string()),
        ("request_datetime", pa.timestamp("us")),
        ("on_scene_datetime", pa.timestamp("us")),
        ("pickup_datetime", pa.timestamp("us")),
        ("dropoff_datetime", pa.timestamp("us")),
        ("PULocationID", pa.int32()),
        ("DOLocationID", pa.int32()),
        ("trip_miles", pa.float64()),
        ("trip_time", pa.int64()),
        ("base_passenger_fare", pa.float64()),
        ("tolls", pa.float64()),
        ("bcf", pa.float64()),
        ("sales_tax", pa.float64()),
        ("congestion_surcharge", pa.float64()),
        ("airport_fee", pa.float64()),
        ("tips", pa.float64()),
        ("driver_pay", pa.float64()),
        ("shared_request_flag", pa.large_string()),
        ("shared_match_flag", pa.large_string()),
        ("access_a_ride_flag", pa.large_string()),
        ("wav_request_flag", pa.large_string()),
        ("wav_match_flag", pa.large_string()),
        ("cbd_congestion_fee", pa.float64()),
    ]
)

# One valid March 2026 Uber trip (Tuesday 08:00, 5-minute wait).
# Fare before tip: 20.00 + 0 + 0.50 + 1.78 + 2.75 + 0 + 1.50 = 26.53.
VALID_TRIP = {
    "hvfhs_license_num": "HV0003",
    "dispatching_base_num": "B03404",
    "originating_base_num": "B03404",
    "request_datetime": "2026-03-10 07:55:00",
    "on_scene_datetime": "2026-03-10 07:59:00",
    "pickup_datetime": "2026-03-10 08:00:00",
    "dropoff_datetime": "2026-03-10 08:15:00",
    "PULocationID": 161,
    "DOLocationID": 237,
    "trip_miles": 2.5,
    "trip_time": 900,
    "base_passenger_fare": 20.0,
    "tolls": 0.0,
    "bcf": 0.5,
    "sales_tax": 1.78,
    "congestion_surcharge": 2.75,
    "airport_fee": 0.0,
    "tips": 3.0,
    "driver_pay": 15.0,
    "shared_request_flag": "N",
    "shared_match_flag": "N",
    "access_a_ride_flag": "N",
    "wav_request_flag": "N",
    "wav_match_flag": "N",
    "cbd_congestion_fee": 1.5,
}

# Every fare part is zero, so a test can set the fare it needs exactly.
NO_FARE = {
    "base_passenger_fare": 0.0,
    "tolls": 0.0,
    "bcf": 0.0,
    "sales_tax": 0.0,
    "congestion_surcharge": 0.0,
    "airport_fee": 0.0,
    "cbd_congestion_fee": 0.0,
}


def _value(value, field):
    if isinstance(value, str) and pa.types.is_timestamp(field.type):
        return datetime.fromisoformat(value)
    return value


def make_table(*overrides, drop=()):
    """One trip per override dict, each starting from VALID_TRIP, as an
    Arrow table with the raw schema. Columns in drop are left out."""
    rows = [{**VALID_TRIP, **row} for row in overrides]
    fields = [field for field in RAW_SCHEMA if field.name not in drop]
    arrays = [
        pa.array([_value(row[field.name], field) for row in rows], type=field.type)
        for field in fields
    ]
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def write_trips(path, *overrides, drop=()):
    """Write make_table(*overrides) to a Parquet file."""
    pq.write_table(make_table(*overrides, drop=drop), path)


def make_trips(*overrides):
    """Trips as read_batches() yields them: our names, booleans for the
    provider and shared flags."""
    return to_frame(make_table(*overrides))
