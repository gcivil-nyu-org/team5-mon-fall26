"""Per-cell totals for zone and route statistics.

Each month gives partial totals (count, sums, min, max) per cell. They are
merged across months and turned into averages only at the end, so the
result is exact and does not depend on the order of the months.
"""

from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

ZONE_KEYS = ["pickup_zone_id", "day_of_week", "hour"]
ROUTE_KEYS = ["pickup_zone_id", "dropoff_zone_id", "day_of_week", "hour"]

PARTIAL_COLUMNS = [
    "trip_count",
    "duration_sum_s",
    "fare_sum_cents",
    "fare_min_cents",
    "fare_max_cents",
]

# How each partial column is merged across months.
_MERGE = {
    "trip_count": "sum",
    "duration_sum_s": "sum",
    "fare_sum_cents": "sum",
    "fare_min_cents": "min",
    "fare_max_cents": "max",
}

CENT = Decimal("0.01")


def partial_totals(kept, keys):
    """Totals per cell for one month of cleaned trips, indexed by keys."""
    partials = kept.groupby(keys, sort=True).agg(
        trip_count=("fare_cents", "size"),
        duration_sum_s=("duration_s", "sum"),
        fare_sum_cents=("fare_cents", "sum"),
        fare_min_cents=("fare_cents", "min"),
        fare_max_cents=("fare_cents", "max"),
    )
    return partials.astype("int64")


def combine_partials(acc, part):
    """Merge one month's partial totals into the running totals."""
    if acc is None:
        return part
    combined = pd.concat([acc, part]).groupby(level=list(acc.index.names), sort=True)
    return combined.agg(_MERGE)[PARTIAL_COLUMNS].astype("int64")


def finalize(partials):
    """Final per-cell stats: key columns, trip_count, avg_duration_min,
    and fares still in integer cents (converted to Decimal when written)."""
    stats = partials.reset_index()
    stats["avg_duration_min"] = stats["duration_sum_s"] / stats["trip_count"] / 60
    keys = list(partials.index.names)
    return stats[
        keys
        + [
            "trip_count",
            "avg_duration_min",
            "fare_min_cents",
            "fare_sum_cents",
            "fare_max_cents",
        ]
    ]


def cents_to_decimal(cents):
    """1890 -> Decimal("18.90")."""
    return Decimal(int(cents)).scaleb(-2)


def average_cents_to_decimal(sum_cents, count):
    """Average fare in dollars, rounded half up to the cent."""
    return (Decimal(int(sum_cents)) / (int(count) * 100)).quantize(CENT, ROUND_HALF_UP)
