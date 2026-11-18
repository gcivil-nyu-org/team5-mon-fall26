"""Cleaning rules for one batch of High Volume FHV trips (see
docs/decisions.md, "Rideshare import").

Pure DataFrame in, DataFrame out: no file or database access here. The
limits are editable in the admin (US41 #115, zones.CleaningRules, a
record of its own) and start at the taxi import's values; the import
passes them in as RideshareLimits.
"""

from dataclasses import dataclass

import pandas as pd

from zones.importer.clean import (
    UNKNOWN_ZONE_IDS,
    Limits,
    duration_seconds,
    limit_labels,
    month_bounds,
    remove_failed,
)


@dataclass(frozen=True)
class RideshareLimits(Limits):
    """The taxi limits plus the wait limits. A wait outside them is left
    out of the wait average; the trip is still kept for fare and
    duration."""

    min_wait_s: int = 0
    max_wait_s: int = 60 * 60


DEFAULT_LIMITS = RideshareLimits()

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


def rules(limits=DEFAULT_LIMITS):
    """(key, label) per rule, in counting order: each removed trip is
    counted under the first rule it fails."""
    labels = limit_labels(limits)
    return (
        ("pickup_outside_month", "Pickup outside the file's month"),
        ("other_provider", "Provider not Uber or Lyft"),
        ("shared_ride", "Shared ride (requested or matched)"),
        ("unknown_zone", "Unknown pickup or dropoff zone"),
        ("fare_not_positive", "Base fare <= 0 or fare before tip <= 0"),
        ("fare_over_max", labels["fare_over_max"]),
        ("bad_distance", labels["bad_distance"]),
        ("bad_duration", labels["bad_duration"]),
    )


# The rules with the starting limits. Only the labels depend on the limits.
RULES = rules()


def _fare_before_tip_cents(trips):
    # skipna=False: a missing part makes the fare missing, so it fails the
    # fare rule. Rounding to whole cents removes float noise.
    return (trips[FARE_PARTS].sum(axis=1, skipna=False) * 100).round()


def _wait_seconds(trips):
    return (trips["pickup_at"] - trips["request_at"]).dt.total_seconds()


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
    miles = trips["trip_miles"]

    return {
        "pickup_outside_month": ~((pickup >= start) & (pickup < end)),
        "other_provider": ~(trips["is_uber"] | trips["is_lyft"]),
        "shared_ride": trips["shared_request"] | trips["shared_match"],
        "unknown_zone": ~(
            trips["pickup_zone_id"].isin(valid_zones)
            & trips["dropoff_zone_id"].isin(valid_zones)
        ),
        "fare_not_positive": ~((trips["base_passenger_fare"] > 0) & (fare_cents > 0)),
        "fare_over_max": fare_cents > limits.max_fare_cents,
        "bad_distance": ~(
            (miles > limits.min_distance_mi) & (miles <= limits.max_distance_mi)
        ),
        "bad_duration": ~(
            (duration_s >= limits.min_duration_s)
            & (duration_s <= limits.max_duration_s)
        ),
    }


def clean_trips(trips, month, known_zone_ids, limits=DEFAULT_LIMITS):
    """Remove the trips that fail any rule.

    Returns (kept, removed). kept has pickup_zone_id, dropoff_zone_id,
    day_of_week (Monday=0), hour, duration_s, fare_cents,
    miles_hundredths, wait_s and wait_valid. wait_s is 0 where wait_valid
    is False, so it can be summed directly. removed maps each rule key,
    in RULES order, to the trips counted under it.
    """
    masks = rule_masks(trips, month, known_zone_ids, limits)
    removed_mask, removed = remove_failed(masks, RULES, trips.index)

    rows = trips[~removed_mask]
    wait_s = _wait_seconds(rows)
    wait_valid = (wait_s >= limits.min_wait_s) & (wait_s <= limits.max_wait_s)
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
