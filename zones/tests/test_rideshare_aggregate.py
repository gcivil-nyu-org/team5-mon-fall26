import math

import pandas as pd
from django.test import SimpleTestCase
from pandas.testing import assert_frame_equal

from zones.importer.aggregate import ROUTE_KEYS, ZONE_KEYS
from zones.importer.rideshare.aggregate import (
    PARTIAL_COLUMNS,
    STAT_COLUMNS,
    Totals,
    combine_partials,
    finalize,
    partial_totals,
)
from zones.importer.rideshare.clean import clean_trips
from zones.tests.importer_helpers import KNOWN_ZONE_IDS
from zones.tests.rideshare_helpers import make_kept, make_trips

# (pickup, dropoff, day, hour, duration_s, fare_cents, miles_hundredths, wait_s)
# The 161 -> 237 Tuesday 8:00 cell is checked by hand below.
HAND_CHECKED = make_kept(
    (161, 237, 1, 8, 600, 1890, 250, 300),
    (161, 237, 1, 8, 660, 1865, 175, None),
    (161, 237, 1, 8, 900, 2001, 333, 120),
    (161, 230, 1, 8, 300, 1500, 100, 60),
    (4, 237, 6, 23, 1200, 3000, 900, None),
    (4, 237, 6, 23, 600, 2000, 500, None),
    (4, 161, 6, 23, 300, 750, 0, 600),
)

# Trips spread so that, in any split below, a cell's min, max and valid
# waits come from different batches.
SPREAD = make_kept(
    (161, 237, 0, 8, 600, 1500, 250, 240),
    (4, 237, 6, 23, 1200, 3000, 900, None),
    (161, 237, 0, 8, 660, 1890, 300, None),
    (230, 161, 2, 17, 1500, 2500, 410, 30),
    (161, 237, 0, 8, 700, 900, 120, 600),
    (161, 230, 0, 8, 420, 1700, 199, 0),
    (4, 237, 6, 23, 600, 2000, 500, 3600),
    (161, 237, 0, 8, 100, 4200, 1000, 90),
    (230, 161, 2, 17, 1600, 2600, 400, None),
)


def cell(partials, *key):
    return partials.loc[key].tolist()


def stats_row(stats, **key):
    match = stats
    for column, value in key.items():
        match = match[match[column] == value]
    assert len(match) == 1, match
    return match.iloc[0]


def totals_of(*batches, flush_rows=None):
    totals = Totals() if flush_rows is None else Totals(flush_rows=flush_rows)
    for batch in batches:
        totals.add(batch)
    return totals.stats()


def split(kept, *bounds):
    edges = [0, *bounds, len(kept)]
    return [kept.iloc[a:b] for a, b in zip(edges, edges[1:])]


class PartialTotalsTests(SimpleTestCase):
    def test_route_cell_hand_checked(self):
        routes = partial_totals(HAND_CHECKED, ROUTE_KEYS)

        self.assertEqual(list(routes.index.names), ROUTE_KEYS)
        self.assertEqual(list(routes.columns), PARTIAL_COLUMNS)
        # count, duration sum, fare sum/min/max, wait sum, wait count, miles
        self.assertEqual(
            cell(routes, 161, 237, 1, 8),
            [3, 2160, 5756, 1865, 2001, 420, 2, 758],
        )

    def test_invalid_waits_are_not_summed_or_counted(self):
        routes = partial_totals(HAND_CHECKED, ROUTE_KEYS)

        self.assertEqual(routes.loc[(4, 237, 6, 23), "wait_count"], 0)
        self.assertEqual(routes.loc[(4, 237, 6, 23), "wait_sum_s"], 0)
        self.assertEqual(routes.loc[(4, 237, 6, 23), "trip_count"], 2)

    def test_zone_cells_come_from_the_trips_not_the_routes(self):
        zones = partial_totals(HAND_CHECKED, ZONE_KEYS)

        self.assertEqual(list(zones.index.names), ZONE_KEYS)
        self.assertEqual(
            cell(zones, 161, 1, 8),
            [4, 2460, 7256, 1500, 2001, 480, 3, 858],
        )
        self.assertEqual(
            cell(zones, 4, 6, 23), [3, 2100, 5750, 750, 3000, 600, 1, 1400]
        )

    def test_columns_are_int64(self):
        routes = partial_totals(HAND_CHECKED, ROUTE_KEYS)

        self.assertEqual(set(routes.dtypes.astype(str)), {"int64"})

    def test_no_trips_gives_no_cells(self):
        routes = partial_totals(HAND_CHECKED.iloc[0:0], ROUTE_KEYS)

        self.assertEqual(len(routes), 0)
        self.assertEqual(list(routes.columns), PARTIAL_COLUMNS)


class CombinePartialsTests(SimpleTestCase):
    def test_sums_min_max_and_waits_across_parts(self):
        a, b = split(SPREAD, 4)
        combined = combine_partials(
            partial_totals(a, ROUTE_KEYS), partial_totals(b, ROUTE_KEYS)
        )

        self.assertEqual(
            cell(combined, 161, 237, 0, 8),
            [4, 2060, 8490, 900, 4200, 240 + 600 + 90, 3, 1670],
        )

    def test_first_part_is_returned_as_is(self):
        part = partial_totals(SPREAD, ZONE_KEYS)

        self.assertIs(combine_partials(None, part), part)


class FinalizeTests(SimpleTestCase):
    def test_columns(self):
        stats = finalize(partial_totals(HAND_CHECKED, ROUTE_KEYS))

        self.assertEqual(list(stats.columns), ROUTE_KEYS + STAT_COLUMNS)

    def test_hand_checked_cell(self):
        stats = finalize(partial_totals(HAND_CHECKED, ROUTE_KEYS))
        row = stats_row(stats, pickup_zone_id=161, dropoff_zone_id=237, hour=8)

        self.assertEqual(row.trip_count, 3)
        self.assertEqual(row.avg_duration_min, 2160 / 3 / 60)  # 12.0
        self.assertEqual(row.avg_wait_min, (300 + 120) / 2 / 60)  # 3.5, 2 valid
        self.assertEqual(row.wait_count, 2)
        self.assertEqual(
            [row.fare_min_cents, row.fare_sum_cents, row.fare_max_cents],
            [1865, 5756, 2001],
        )
        self.assertEqual(row.miles_sum_hundredths, 758)

    def test_cell_with_only_invalid_waits_has_no_average(self):
        stats = finalize(partial_totals(HAND_CHECKED, ROUTE_KEYS))
        row = stats_row(stats, pickup_zone_id=4, dropoff_zone_id=237)

        self.assertEqual(row.wait_count, 0)
        self.assertTrue(math.isnan(row.avg_wait_min))
        self.assertEqual(row.trip_count, 2)


class SplitInvarianceTests(SimpleTestCase):
    """However the trips are split into batches and months, the final
    rows are the same as one pass over all of them."""

    def assert_same(self, got, want):
        for got_stats, want_stats in zip(got, want):
            assert_frame_equal(got_stats, want_stats)

    def test_one_batch_matches_one_groupby(self):
        zone_stats, route_stats = totals_of(SPREAD)

        assert_frame_equal(zone_stats, finalize(partial_totals(SPREAD, ZONE_KEYS)))
        assert_frame_equal(route_stats, finalize(partial_totals(SPREAD, ROUTE_KEYS)))

    def test_several_batches_match_one_batch(self):
        one = totals_of(SPREAD)
        splits = {
            "halves": split(SPREAD, 4),
            "thirds": split(SPREAD, 3, 6),
            "one trip each": split(SPREAD, *range(1, len(SPREAD))),
            "reversed": split(SPREAD, 2, 5)[::-1],
        }
        for name, batches in splits.items():
            for flush_rows in (1, 3, 10**6):
                with self.subTest(split=name, flush_rows=flush_rows):
                    self.assert_same(totals_of(*batches, flush_rows=flush_rows), one)

    def test_empty_batch_changes_nothing(self):
        self.assert_same(totals_of(SPREAD.iloc[0:0], SPREAD), totals_of(SPREAD))

    def test_stats_can_be_read_while_adding(self):
        totals = Totals(flush_rows=10**6)
        a, b = split(SPREAD, 5)
        totals.add(a)
        self.assert_same(totals.stats(), totals_of(a))

        totals.add(b)

        self.assert_same(totals.stats(), totals_of(SPREAD))

    def test_no_batches_gives_no_rows(self):
        zone_stats, route_stats = Totals().stats()

        self.assertEqual(list(zone_stats.columns), ZONE_KEYS + STAT_COLUMNS)
        self.assertEqual(list(route_stats.columns), ROUTE_KEYS + STAT_COLUMNS)
        self.assertEqual((len(zone_stats), len(route_stats)), (0, 0))

    def test_two_months_in_batches_match_one_batch(self):
        # Raw trips through clean_trips, so the whole path from a cleaned
        # batch is covered. The same Tuesday-8:00 cell gets its fare min
        # in March, its max in April and a wait left out in each month.
        march = [
            {"pickup_datetime": "2026-03-10 08:00:00", "base_passenger_fare": 9.0},
            {"request_datetime": "2026-03-10 08:30:00"},  # negative wait
            {
                "request_datetime": "2026-03-17 08:05:00",
                "pickup_datetime": "2026-03-17 08:10:00",
                "dropoff_datetime": "2026-03-17 08:25:00",
            },
            {"PULocationID": 4, "DOLocationID": 161},
        ]
        april = [
            {
                "request_datetime": "2026-04-07 08:00:00",
                "pickup_datetime": "2026-04-07 08:05:00",
                "dropoff_datetime": "2026-04-07 08:30:00",
                "base_passenger_fare": 80.0,
                "trip_miles": 12.34,
            },
            {
                "request_datetime": "2026-04-14 06:00:00",  # over 60 minutes
                "pickup_datetime": "2026-04-14 08:20:00",
                "dropoff_datetime": "2026-04-14 08:40:00",
            },
            {
                "request_datetime": "2026-04-14 08:58:00",
                "pickup_datetime": "2026-04-14 08:59:00",
                "dropoff_datetime": "2026-04-14 09:20:00",
            },
        ]

        def kept(month, rows):
            return clean_trips(make_trips(*rows), month, KNOWN_ZONE_IDS)[0]

        batches = [
            kept("2026-03", march[:2]),
            kept("2026-04", april[:1]),
            kept("2026-03", march[2:]),
            kept("2026-04", april[1:]),
        ]
        all_trips = pd.concat(batches, ignore_index=True)
        self.assertEqual(len(all_trips), 7)

        zone_stats, route_stats = totals_of(*batches, flush_rows=2)
        self.assert_same((zone_stats, route_stats), totals_of(all_trips))

        row = stats_row(route_stats, pickup_zone_id=161, dropoff_zone_id=237, hour=8)
        self.assertEqual(row.trip_count, 6)
        self.assertEqual(row.wait_count, 4)  # one negative, one over 60 min
        self.assertEqual(row.fare_min_cents, 9 * 100 + 653)
        self.assertEqual(row.fare_max_cents, 80 * 100 + 653)
