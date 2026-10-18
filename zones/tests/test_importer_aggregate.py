from decimal import Decimal

import pandas as pd
from django.test import SimpleTestCase
from pandas.testing import assert_frame_equal

from zones.importer.aggregate import (
    PARTIAL_COLUMNS,
    ROUTE_KEYS,
    ZONE_KEYS,
    average_cents_to_decimal,
    cents_to_decimal,
    combine_partials,
    finalize,
    partial_totals,
)
from zones.tests.importer_helpers import make_kept


# Five Tuesday trips, checked by hand in the tests below.
FIVE_TRIPS = make_kept(
    (161, 237, 1, 8, 600, 1500),
    (161, 230, 1, 8, 900, 2000),
    (161, 237, 1, 8, 1200, 1000),
    (161, 237, 1, 9, 300, 700),
    (4, 237, 1, 8, 480, 1200),
)

MONTH_A = make_kept(
    (161, 237, 0, 8, 600, 1500),
    (161, 237, 0, 8, 660, 1890),
    (4, 237, 6, 23, 1200, 3000),
)
MONTH_B = make_kept(
    (161, 237, 0, 8, 700, 1865),
    (161, 237, 0, 8, 100, 900),
    (230, 161, 2, 17, 1500, 2500),
)


def cell(partials, *key):
    return partials.loc[key].tolist()


class PartialTotalsTests(SimpleTestCase):
    def test_zone_cells_hand_checked(self):
        zones = partial_totals(FIVE_TRIPS, ZONE_KEYS)

        self.assertEqual(list(zones.index.names), ZONE_KEYS)
        self.assertEqual(list(zones.columns), PARTIAL_COLUMNS)
        self.assertEqual(len(zones), 3)
        # count, duration sum, fare sum, fare min, fare max
        self.assertEqual(cell(zones, 161, 1, 8), [3, 2700, 4500, 1000, 2000])
        self.assertEqual(cell(zones, 161, 1, 9), [1, 300, 700, 700, 700])
        self.assertEqual(cell(zones, 4, 1, 8), [1, 480, 1200, 1200, 1200])

    def test_zone_cells_group_by_pickup_only(self):
        # Trips from 161 at 8:00 go to 237 and 230 but share one zone cell.
        zones = partial_totals(FIVE_TRIPS, ZONE_KEYS)

        self.assertEqual(zones.loc[(161, 1, 8), "trip_count"], 3)

    def test_route_cells_keep_pairs_apart(self):
        routes = partial_totals(FIVE_TRIPS, ROUTE_KEYS)

        self.assertEqual(list(routes.index.names), ROUTE_KEYS)
        self.assertEqual(len(routes), 4)
        self.assertEqual(cell(routes, 161, 237, 1, 8), [2, 1800, 2500, 1000, 1500])
        self.assertEqual(cell(routes, 161, 230, 1, 8), [1, 900, 2000, 2000, 2000])

    def test_columns_are_int64(self):
        zones = partial_totals(FIVE_TRIPS, ZONE_KEYS)

        self.assertEqual(set(zones.dtypes.astype(str)), {"int64"})

    def test_month_with_no_kept_trips_gives_no_cells(self):
        zones = partial_totals(FIVE_TRIPS.iloc[0:0], ZONE_KEYS)

        self.assertEqual(len(zones), 0)
        self.assertEqual(list(zones.columns), PARTIAL_COLUMNS)


class CombinePartialsTests(SimpleTestCase):
    def test_first_month_is_returned_as_is(self):
        part = partial_totals(MONTH_A, ROUTE_KEYS)

        self.assertIs(combine_partials(None, part), part)

    def test_combined_months_equal_one_pass_over_all_trips(self):
        for keys in (ZONE_KEYS, ROUTE_KEYS):
            with self.subTest(keys=keys):
                combined = combine_partials(
                    partial_totals(MONTH_A, keys), partial_totals(MONTH_B, keys)
                )
                one_pass = partial_totals(pd.concat([MONTH_A, MONTH_B]), keys)

                assert_frame_equal(combined, one_pass)
                assert_frame_equal(finalize(combined), finalize(one_pass))

    def test_month_order_does_not_matter(self):
        a = partial_totals(MONTH_A, ROUTE_KEYS)
        b = partial_totals(MONTH_B, ROUTE_KEYS)

        assert_frame_equal(combine_partials(a, b), combine_partials(b, a))

    def test_sums_min_and_max_across_months(self):
        combined = combine_partials(
            partial_totals(MONTH_A, ROUTE_KEYS), partial_totals(MONTH_B, ROUTE_KEYS)
        )

        self.assertEqual(
            cell(combined, 161, 237, 0, 8),
            [4, 600 + 660 + 700 + 100, 1500 + 1890 + 1865 + 900, 900, 1890],
        )

    def test_cells_from_only_one_month_are_kept(self):
        combined = combine_partials(
            partial_totals(MONTH_A, ROUTE_KEYS), partial_totals(MONTH_B, ROUTE_KEYS)
        )

        self.assertEqual(cell(combined, 4, 237, 6, 23), [1, 1200, 3000, 3000, 3000])
        self.assertEqual(cell(combined, 230, 161, 2, 17), [1, 1500, 2500, 2500, 2500])
        self.assertEqual(len(combined), 3)

    def test_empty_month_changes_nothing(self):
        acc = partial_totals(MONTH_A, ZONE_KEYS)
        empty = partial_totals(MONTH_A.iloc[0:0], ZONE_KEYS)

        assert_frame_equal(combine_partials(acc, empty), acc)


class FinalizeTests(SimpleTestCase):
    def test_columns(self):
        stats = finalize(partial_totals(FIVE_TRIPS, ZONE_KEYS))

        self.assertEqual(
            list(stats.columns),
            ZONE_KEYS
            + [
                "trip_count",
                "avg_duration_min",
                "fare_min_cents",
                "fare_sum_cents",
                "fare_max_cents",
            ],
        )

    def test_average_duration_in_minutes(self):
        stats = finalize(partial_totals(FIVE_TRIPS, ZONE_KEYS)).set_index(ZONE_KEYS)

        self.assertEqual(stats.loc[(161, 1, 8), "avg_duration_min"], 2700 / 3 / 60)
        self.assertEqual(stats.loc[(161, 1, 9), "avg_duration_min"], 5.0)

    def test_every_cell_is_kept_even_with_one_trip(self):
        stats = finalize(partial_totals(FIVE_TRIPS, ROUTE_KEYS))

        self.assertEqual(len(stats), 4)
        self.assertEqual(sorted(stats["trip_count"]), [1, 1, 1, 2])


class DecimalTests(SimpleTestCase):
    def test_cents_to_decimal(self):
        self.assertEqual(str(cents_to_decimal(1890)), "18.90")
        self.assertEqual(str(cents_to_decimal(5)), "0.05")
        self.assertEqual(str(cents_to_decimal(50000)), "500.00")

    def test_cents_to_decimal_accepts_numpy_ints(self):
        stats = finalize(partial_totals(FIVE_TRIPS, ZONE_KEYS))

        self.assertEqual(cents_to_decimal(stats["fare_min_cents"].iloc[0]), Decimal("12.00"))

    def test_average_rounds_half_up(self):
        self.assertEqual(average_cents_to_decimal(1, 2), Decimal("0.01"))  # 0.005
        self.assertEqual(average_cents_to_decimal(2, 3), Decimal("0.01"))  # 0.00667
        self.assertEqual(average_cents_to_decimal(1890 + 1865, 2), Decimal("18.78"))  # 18.775
        self.assertEqual(average_cents_to_decimal(1, 3), Decimal("0.00"))  # 0.00333

    def test_average_has_two_decimal_places(self):
        self.assertEqual(str(average_cents_to_decimal(3000, 2)), "15.00")
