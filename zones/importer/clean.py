"""Cleaning rules for one month of trips (see docs/decisions.md).

Pure DataFrame in, DataFrame out: no file or database access here.
"""

import pandas as pd

MAX_FARE_CENTS = 50_000
MAX_DISTANCE_MI = 100
MIN_DURATION_S = 60
MAX_DURATION_S = 180 * 60
VOIDED_PAYMENT_TYPE = 6
UNKNOWN_ZONE_IDS = {264, 265}

# Each removed trip is counted under the first rule it fails, in this order.
RULES = (
    ("pickup_outside_month", "Pickup outside the file's month"),
    ("voided", "Voided trip (payment_type 6)"),
    ("unknown_zone", "Unknown pickup or dropoff zone"),
    ("fare_not_positive", "Fare <= 0 or fare before tip <= 0"),
    ("fare_over_max", "Fare before tip > $500"),
    ("bad_distance", "Distance <= 0 or > 100 miles"),
    ("bad_duration", "Duration < 1 or > 180 minutes"),
)


def month_bounds(month):
    """Start of the month "YYYY-MM" and start of the next month."""
    start = pd.Timestamp(f"{month}-01")
    return start, start + pd.offsets.MonthBegin(1)


def _fare_before_tip_cents(trips):
    # Rounding to whole cents removes float noise like 22.200000000000003.
    return ((trips["total_amount"] - trips["tip_amount"]) * 100).round()


def _duration_seconds(trips):
    return (trips["dropoff_at"] - trips["pickup_at"]).dt.total_seconds()


def rule_masks(trips, month, known_zone_ids):
    """One boolean Series per rule, True where the trip fails it.

    Rules are written as "not (keep condition)" so that a missing value
    (NaN or NaT) fails the rule instead of slipping through.
    """
    start, end = month_bounds(month)
    pickup = trips["pickup_at"]
    valid_zones = list(set(known_zone_ids) - UNKNOWN_ZONE_IDS)
    fare_cents = _fare_before_tip_cents(trips)
    duration_s = _duration_seconds(trips)
    distance = trips["trip_distance"]

    return {
        "pickup_outside_month": ~((pickup >= start) & (pickup < end)),
        "voided": trips["payment_type"] == VOIDED_PAYMENT_TYPE,
        "unknown_zone": ~(
            trips["pickup_zone_id"].isin(valid_zones)
            & trips["dropoff_zone_id"].isin(valid_zones)
        ),
        "fare_not_positive": ~((trips["fare_amount"] > 0) & (fare_cents > 0)),
        "fare_over_max": fare_cents > MAX_FARE_CENTS,
        "bad_distance": ~((distance > 0) & (distance <= MAX_DISTANCE_MI)),
        "bad_duration": ~(
            (duration_s >= MIN_DURATION_S) & (duration_s <= MAX_DURATION_S)
        ),
    }


def clean_trips(trips, month, known_zone_ids):
    """Remove the trips that fail any rule.

    Returns (kept, removed). kept has pickup_zone_id, dropoff_zone_id,
    day_of_week (Monday=0), hour, duration_s and fare_cents. removed maps
    each rule key, in RULES order, to the trips counted under it.
    """
    masks = rule_masks(trips, month, known_zone_ids)
    already_removed = pd.Series(False, index=trips.index)
    removed = {}
    for key, _ in RULES:
        removed[key] = int((masks[key] & ~already_removed).sum())
        already_removed = already_removed | masks[key]

    rows = trips[~already_removed]
    kept = pd.DataFrame(
        {
            "pickup_zone_id": rows["pickup_zone_id"].astype("int16"),
            "dropoff_zone_id": rows["dropoff_zone_id"].astype("int16"),
            "day_of_week": rows["pickup_at"].dt.dayofweek.astype("int8"),
            "hour": rows["pickup_at"].dt.hour.astype("int8"),
            "duration_s": _duration_seconds(rows).astype("int64"),
            "fare_cents": _fare_before_tip_cents(rows).astype("int64"),
        }
    )
    return kept.reset_index(drop=True), removed
