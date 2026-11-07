"""Per-cell totals for the rideshare zone and route statistics.

The taxi totals (zones/importer/aggregate.py) plus three columns: the
wait sum and count over trips whose wait is valid, and the miles in
integer hundredths. Every batch, of any month, is reduced to partial
totals; they are merged and turned into averages only at the end, so the
result is exact and does not depend on how the trips were split.
"""

import pandas as pd

from zones.importer import aggregate as taxi
from zones.importer.aggregate import ROUTE_KEYS, ZONE_KEYS

_EXTRA = {
    "wait_sum_s": ("wait_s", "sum"),
    "wait_count": ("wait_valid", "sum"),
    "miles_sum_hundredths": ("miles_hundredths", "sum"),
}

# How each partial column is merged, in column order.
MERGE = {**taxi.MERGE, **{column: "sum" for column in _EXTRA}}
PARTIAL_COLUMNS = list(MERGE)

# Columns of finalize(), after the key columns. Fares and miles stay in
# integer cents and hundredths; they become Decimal only when written.
STAT_COLUMNS = [
    "trip_count",
    "avg_duration_min",
    "fare_min_cents",
    "fare_sum_cents",
    "fare_max_cents",
    "avg_wait_min",
    "wait_count",
    "miles_sum_hundredths",
]

# Batch partials wait in a list until they hold this many rows, then are
# merged into the running totals in one groupby. Merging after every
# batch regroups the whole running total each time: 3x slower on March.
FLUSH_ROWS = 4_000_000


def partial_totals(kept, keys):
    """Totals per cell for one batch of cleaned trips, indexed by keys."""
    return taxi.partial_totals(kept, keys, **_EXTRA)


def combine_partials(acc, part):
    """Merge partial totals (part may repeat a cell) into acc."""
    return taxi.combine_partials(acc, part, MERGE)


def finalize(partials):
    """Final per-cell stats: the key columns, then STAT_COLUMNS.

    avg_wait_min is NaN where wait_count is 0.
    """
    stats = taxi.finalize(partials)
    for column in _EXTRA:
        stats[column] = partials[column].to_numpy()
    wait_count = stats["wait_count"]
    stats["avg_wait_min"] = (stats["wait_sum_s"] / wait_count / 60).where(
        wait_count > 0
    )
    return stats[list(partials.index.names) + STAT_COLUMNS]


def _empty_partials(keys):
    index = pd.MultiIndex.from_arrays([[]] * len(keys), names=keys)
    return pd.DataFrame(0, index=index, columns=PARTIAL_COLUMNS).astype("int64")


class _Cells:
    """Running totals for one set of keys, merged in large steps."""

    def __init__(self, keys, flush_rows):
        self.keys = keys
        self.flush_rows = flush_rows
        self.acc = None
        self.pending = []
        self.pending_rows = 0

    def add(self, kept):
        part = partial_totals(kept, self.keys)
        self.pending.append(part)
        self.pending_rows += len(part)
        if self.pending_rows >= self.flush_rows:
            self.flush()

    def flush(self):
        if self.pending:
            first, *rest = [p for p in (self.acc, *self.pending) if p is not None]
            self.acc = combine_partials(first, pd.concat(rest)) if rest else first
            self.pending = []
            self.pending_rows = 0

    def stats(self):
        self.flush()
        return finalize(
            self.acc if self.acc is not None else _empty_partials(self.keys)
        )


class Totals:
    """Zone and route totals over any number of batches and months.

    Zone cells are grouped from the trips themselves, not summed from
    route cells.
    """

    def __init__(self, flush_rows=FLUSH_ROWS):
        self.zones = _Cells(ZONE_KEYS, flush_rows)
        self.routes = _Cells(ROUTE_KEYS, flush_rows)

    def add(self, kept):
        """Add one batch of trips from clean_trips()."""
        self.zones.add(kept)
        self.routes.add(kept)

    def stats(self):
        """(zone_stats, route_stats) as finalize() returns them."""
        return self.zones.stats(), self.routes.stats()
