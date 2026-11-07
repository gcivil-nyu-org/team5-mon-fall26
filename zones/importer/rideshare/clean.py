"""Cleaning rules for one batch of High Volume FHV trips (see
docs/decisions.md, "Rideshare import").

Pure DataFrame in, DataFrame out: no file or database access here. The
limits are the taxi import's, shared from zones/importer/clean.py.
"""

import pandas as pd

from zones.importer.clean import (
    MAX_DISTANCE_MI,
    MAX_DURATION_S,
    MAX_FARE_CENTS,
    MIN_DURATION_S,
    UNKNOWN_ZONE_IDS,
    duration_seconds,
    month_bounds,
    remove_failed,
)

# A wait outside these limits is left out of the wait average; the trip
# is still kept for fare and duration.
MIN_WAIT_S = 0
MAX_WAIT_S = 60 * 60

# Fare before tip: the 7 parts the rider pays, without tips.
FARE_PARTS = [
    "base_passenger_fare",
    "tolls",
    "bcf",
    "sales_tax",
    "congestion_surcharge",
    "airport_fee",
    "cbd_congestion_fee",
]

# Each removed trip is counted under the first rule it fails, in this order.
RULES = (
    ("pickup_outside_month", "Pickup outside the file's month"),
    ("other_provider", "Provider not Uber or Lyft"),
    ("shared_ride", "Shared ride (requested or matched)"),
    ("unknown_zone", "Unknown pickup or dropoff zone"),
    ("fare_not_positive", "Base fare <= 0 or fare before tip <= 0"),
    ("fare_over_max", "Fare before tip > $500"),
    ("bad_distance", "Distance <= 0 or > 100 miles"),
    ("bad_duration", "Duration < 1 or > 180 minutes"),
)


def _fare_before_tip_cents(trips):
    # skipna=False: a missing part makes the fare missing, so it fails the
    # fare rule. Rounding to whole cents removes float noise.
    return (trips[FARE_PARTS].sum(axis=1, skipna=False) * 100).round()


def _wait_seconds(trips):
    return (trips["pickup_at"] - trips["request_at"]).dt.total_seconds()


def rule_masks(trips, month, known_zone_ids):
    """One boolean Series per rule, True where the trip fails it.

    Rules are written as "not (keep condition)" so that a missing value
    (NaN or NaT) fails the rule instead of slipping through.
    """
    start, end = month_bounds(month)
    pickup = trips["pickup_at"]
    valid_zones = list(set(known_zone_ids) - UNKNOWN_ZONE_IDS)
    fare_cents = _fare_before_tip_cents(trips)
    duration_s = duration_seconds(trips)
    miles = trips["trip_miles"]

    return {
        "pickup_outside_month": ~((pickup >= start) & (pickup < end)),
        "other_provider": ~(trips["is_uber"] | trips["is_lyft"]),
        "shared_ride": trips["shared_request"] | trips["shared_match"],
        "unknown_zone": ~(
            trips["pickup_zone_id"].isin(valid_zones)
            & trips["dropoff_zone_id"].isin(valid_zones)
        ),
        "fare_not_positive": ~(
            (trips["base_passenger_fare"] > 0) & (fare_cents > 0)
        ),
        "fare_over_max": fare_cents > MAX_FARE_CENTS,
        "bad_distance": ~((miles > 0) & (miles <= MAX_DISTANCE_MI)),
        "bad_duration": ~(
            (duration_s >= MIN_DURATION_S) & (duration_s <= MAX_DURATION_S)
        ),
    }


def clean_trips(trips, month, known_zone_ids):
    """Remove the trips that fail any rule.

    Returns (kept, removed). kept has pickup_zone_id, dropoff_zone_id,
    day_of_week (Monday=0), hour, duration_s, fare_cents,
    miles_hundredths, wait_s and wait_valid. wait_s is 0 where wait_valid
    is False, so it can be summed directly. removed maps each rule key,
    in RULES order, to the trips counted under it.
    """
    masks = rule_masks(trips, month, known_zone_ids)
    removed_mask, removed = remove_failed(masks, RULES, trips.index)

    rows = trips[~removed_mask]
    wait_s = _wait_seconds(rows)
    wait_valid = (wait_s >= MIN_WAIT_S) & (wait_s <= MAX_WAIT_S)
    kept = pd.DataFrame(
        {
            "pickup_zone_id": rows["pickup_zone_id"].astype("int16"),
            "dropoff_zone_id": rows["dropoff_zone_id"].astype("int16"),
            "day_of_week": rows["pickup_at"].dt.dayofweek.astype("int8"),
            "hour": rows["pickup_at"].dt.hour.astype("int8"),
            "duration_s": duration_seconds(rows).astype("int64"),
            "fare_cents": _fare_before_tip_cents(rows).astype("int64"),
            "miles_hundredths": (rows["trip_miles"] * 100).round().astype("int64"),
            "wait_s": wait_s.where(wait_valid, 0).astype("int64"),
            "wait_valid": wait_valid,
        }
    )
    return kept.reset_index(drop=True), removed


def add_removed(*counts):
    """Removed counts added up rule by rule, for example across batches."""
    return {key: sum(count[key] for count in counts) for key, _ in RULES}
