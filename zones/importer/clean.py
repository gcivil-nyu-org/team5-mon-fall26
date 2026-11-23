"""Cleaning rules for one month of trips (see docs/decisions.md).

Pure DataFrame in, DataFrame out: no file or database access here. The
fare, distance and duration limits are editable in the admin (US41 #115,
zones.CleaningRules); the import reads them and passes them in as Limits.
"""

from dataclasses import dataclass

import pandas as pd

VOIDED_PAYMENT_TYPE = 6
UNKNOWN_ZONE_IDS = {264, 265}


@dataclass(frozen=True)
class Limits:
    """The editable limits, in the units the rules compare. The defaults
    are the starting values (the limits before US41)."""

    max_fare_cents: int = 50_000
    min_distance_mi: float = 0
    max_distance_mi: float = 100
    min_duration_s: int = 60
    max_duration_s: int = 180 * 60


DEFAULT_LIMITS = Limits()


def number_text(value):
    """100.0 -> "100", 0.25 -> "0.25": for rule labels."""
    return f"{value:g}"


def fare_text(cents):
    """50000 -> "$500", 45050 -> "$450.50"."""
    if cents % 100 == 0:
        return f"${cents // 100}"
    return f"${cents / 100:.2f}"


def limit_labels(limits):
    """Labels of the fare, distance and duration rules, with the limits in
    them. At the starting values they are the labels from before US41."""
    return {
        "fare_over_max": f"Fare before tip > {fare_text(limits.max_fare_cents)}",
        "bad_distance": (
            f"Distance <= {number_text(limits.min_distance_mi)} "
            f"or > {number_text(limits.max_distance_mi)} miles"
        ),
        "bad_duration": (
            f"Duration < {number_text(limits.min_duration_s / 60)} "
            f"or > {number_text(limits.max_duration_s / 60)} minutes"
        ),
    }


def rules(limits=DEFAULT_LIMITS):
    """(key, label) per rule, in counting order: each removed trip is
    counted under the first rule it fails."""
    labels = limit_labels(limits)
    return (
        ("pickup_outside_month", "Pickup outside the file's month"),
        ("voided", "Voided trip (payment_type 6)"),
        ("unknown_zone", "Unknown pickup or dropoff zone"),
        ("fare_not_positive", "Fare <= 0 or fare before tip <= 0"),
        ("fare_over_max", labels["fare_over_max"]),
        ("bad_distance", labels["bad_distance"]),
        ("bad_duration", labels["bad_duration"]),
    )


# The rules with the starting limits. Only the labels depend on the limits.
RULES = rules()


def month_bounds(month):
    """Start of the month "YYYY-MM" and start of the next month."""
    start = pd.Timestamp(f"{month}-01")
    return start, start + pd.offsets.MonthBegin(1)


def _fare_before_tip_cents(trips):
    # Rounding to whole cents removes float noise like 22.200000000000003.
    return ((trips["total_amount"] - trips["tip_amount"]) * 100).round()


def duration_seconds(trips):
    return (trips["dropoff_at"] - trips["pickup_at"]).dt.total_seconds()


def remove_failed(masks, rules, index):
    """Count each trip once, under the first rule (in rules order) it fails.

    Returns (removed_mask, removed) where removed maps each rule key, in
    rules order, to the number of trips counted under it.
    """
    removed_mask = pd.Series(False, index=index)
    removed = {}
    for key, _ in rules:
        removed[key] = int((masks[key] & ~removed_mask).sum())
        removed_mask = removed_mask | masks[key]
    return removed_mask, removed


def rule_masks(trips, month, known_zone_ids, limits=DEFAULT_LIMITS):
    """One boolean Series per rule, True where the trip fails it.

    Rules are written as "not (keep condition)" so that a missing value
    (NaN or NaT) fails the rule instead of slipping through.
    """
    start, end = month_bounds(month)
    pickup = trips["pickup_at"]
    valid_zones = list(set(known_zone_ids) - UNKNOWN_ZONE_IDS)
    fare_cents = _fare_before_tip_cents(trips)
    duration_s = duration_seconds(trips)
    distance = trips["trip_distance"]

    return {
        "pickup_outside_month": ~((pickup >= start) & (pickup < end)),
        "voided": trips["payment_type"] == VOIDED_PAYMENT_TYPE,
        "unknown_zone": ~(
            trips["pickup_zone_id"].isin(valid_zones)
            & trips["dropoff_zone_id"].isin(valid_zones)
        ),
        "fare_not_positive": ~((trips["fare_amount"] > 0) & (fare_cents > 0)),
        "fare_over_max": fare_cents > limits.max_fare_cents,
        "bad_distance": ~(
            (distance > limits.min_distance_mi) & (distance <= limits.max_distance_mi)
        ),
        "bad_duration": ~(
            (duration_s >= limits.min_duration_s)
            & (duration_s <= limits.max_duration_s)
        ),
    }


def clean_trips(trips, month, known_zone_ids, limits=DEFAULT_LIMITS):
    """Remove the trips that fail any rule.

    Returns (kept, removed). kept has pickup_zone_id, dropoff_zone_id,
    day_of_week (Monday=0), hour, duration_s and fare_cents. removed maps
    each rule key, in RULES order, to the trips counted under it.
    """
    masks = rule_masks(trips, month, known_zone_ids, limits)
    removed_mask, removed = remove_failed(masks, RULES, trips.index)

    rows = trips[~removed_mask]
    kept = pd.DataFrame(
        {
            "pickup_zone_id": rows["pickup_zone_id"].astype("int16"),
            "dropoff_zone_id": rows["dropoff_zone_id"].astype("int16"),
            "day_of_week": rows["pickup_at"].dt.dayofweek.astype("int8"),
            "hour": rows["pickup_at"].dt.hour.astype("int8"),
            "duration_s": duration_seconds(rows).astype("int64"),
            "fare_cents": _fare_before_tip_cents(rows).astype("int64"),
        }
    )
    return kept.reset_index(drop=True), removed
