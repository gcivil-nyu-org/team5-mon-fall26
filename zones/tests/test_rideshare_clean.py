import tempfile
from pathlib import Path

import pandas as pd
from django.test import SimpleTestCase

from zones.importer.rideshare.clean import (
    FARE_PARTS,
    RULES,
    add_removed,
    clean_trips,
)
from zones.importer.rideshare.read import read_batches
from zones.tests.importer_helpers import KNOWN_ZONE_IDS
from zones.tests.rideshare_helpers import NO_FARE, make_trips, write_trips

MONTH = "2026-03"


def run_clean(*overrides):
    return clean_trips(make_trips(*overrides), MONTH, KNOWN_ZONE_IDS)


def fare(dollars, **parts):
    """A trip whose fare before tip is base_passenger_fare=dollars plus parts."""
    return {**NO_FARE, "base_passenger_fare": dollars, **parts}


class CleaningRuleTests(SimpleTestCase):
    """One test per rule: the bad rows are removed and counted under that
    rule, the rows on the allowed boundary are kept, no other rule fires."""

    def assert_rule(self, rule, removed_rows, kept_rows):
        # {} is a fully valid trip, so every test also keeps a normal trip.
        kept, removed = run_clean(*removed_rows, *kept_rows, {})

        expected = {key: 0 for key, _ in RULES}
        expected[rule] = len(removed_rows)
        self.assertEqual(removed, expected)
        self.assertEqual(len(kept), len(kept_rows) + 1)

    def test_pickup_outside_month(self):
        self.assert_rule(
            "pickup_outside_month",
            removed_rows=[
                {
                    "request_datetime": "2026-02-28 23:50:00",
                    "pickup_datetime": "2026-02-28 23:59:59",
                    "dropoff_datetime": "2026-03-01 00:15:00",
                },
                {
                    "request_datetime": "2026-03-31 23:55:00",
                    "pickup_datetime": "2026-04-01 00:00:00",
                    "dropoff_datetime": "2026-04-01 00:15:00",
                },
            ],
            kept_rows=[
                {
                    "request_datetime": "2026-02-28 23:55:00",
                    "pickup_datetime": "2026-03-01 00:00:00",
                    "dropoff_datetime": "2026-03-01 00:15:00",
                },
                {
                    "request_datetime": "2026-03-31 23:55:00",
                    "pickup_datetime": "2026-03-31 23:59:59",
                    "dropoff_datetime": "2026-04-01 00:14:59",
                },
            ],
        )

    def test_other_provider(self):
        self.assert_rule(
            "other_provider",
            removed_rows=[
                {"hvfhs_license_num": "HV0002"},  # Juno
                {"hvfhs_license_num": "HV0004"},  # Via
                {"hvfhs_license_num": ""},
            ],
            kept_rows=[
                {"hvfhs_license_num": "HV0003"},  # Uber
                {"hvfhs_license_num": "HV0005"},  # Lyft
            ],
        )

    def test_shared_ride(self):
        self.assert_rule(
            "shared_ride",
            removed_rows=[
                {"shared_request_flag": "Y", "shared_match_flag": "N"},
                {"shared_request_flag": "N", "shared_match_flag": "Y"},
                {"shared_request_flag": "Y", "shared_match_flag": "Y"},
            ],
            kept_rows=[{"shared_request_flag": "N", "shared_match_flag": "N"}],
        )

    def test_unknown_zone(self):
        self.assert_rule(
            "unknown_zone",
            removed_rows=[
                {"PULocationID": 264},
                {"DOLocationID": 264},
                {"PULocationID": 265},
                {"DOLocationID": 265},
                {"PULocationID": 0},  # not in the lookup
                {"DOLocationID": 266},  # not in the lookup
            ],
            kept_rows=[{"PULocationID": 1, "DOLocationID": 263}],
        )

    def test_fare_not_positive(self):
        self.assert_rule(
            "fare_not_positive",
            removed_rows=[
                fare(0.0),  # fare before tip $0.00
                fare(0.0, tolls=6.94),  # base fare 0
                fare(-5.0, sales_tax=10.0),  # base fare negative
                fare(1.0, sales_tax=-1.0),  # fare before tip 0
                fare(1.0, sales_tax=-2.0),  # fare before tip negative
            ],
            kept_rows=[fare(0.01)],  # $0.01
        )

    def test_fare_over_max(self):
        self.assert_rule(
            "fare_over_max",
            removed_rows=[
                fare(500.01),
                fare(490.0, tolls=6.94, bcf=0.5, cbd_congestion_fee=2.57),  # 500.01
            ],
            kept_rows=[
                fare(500.0),
                fare(490.0, tolls=6.94, bcf=0.5, cbd_congestion_fee=2.56),  # 500.00
                {**fare(500.0), "tips": 100.0},  # tips are not part of the fare
            ],
        )

    def test_bad_distance(self):
        self.assert_rule(
            "bad_distance",
            removed_rows=[
                {"trip_miles": 0.0},
                {"trip_miles": -1.0},
                {"trip_miles": 100.01},
            ],
            kept_rows=[{"trip_miles": 0.01}, {"trip_miles": 100.0}],
        )

    def test_bad_duration(self):
        # VALID_TRIP picks up at 08:00:00.
        self.assert_rule(
            "bad_duration",
            removed_rows=[
                {"dropoff_datetime": "2026-03-10 08:00:59"},  # 59 s
                {"dropoff_datetime": "2026-03-10 11:00:01"},  # 10,801 s
                {"dropoff_datetime": "2026-03-10 08:00:00"},  # zero
                {"dropoff_datetime": "2026-03-10 07:59:00"},  # before pickup
            ],
            kept_rows=[
                {"dropoff_datetime": "2026-03-10 08:01:00"},  # 60 s
                {"dropoff_datetime": "2026-03-10 11:00:00"},  # 10,800 s
            ],
        )

    def test_missing_values_are_removed_by_their_rule(self):
        cases = [
            ({"pickup_datetime": None}, "pickup_outside_month"),
            ({"hvfhs_license_num": None}, "other_provider"),
            ({"shared_request_flag": None}, "shared_ride"),
            ({"shared_match_flag": None}, "shared_ride"),
            ({"PULocationID": None}, "unknown_zone"),
            ({"DOLocationID": None}, "unknown_zone"),
            *[({part: None}, "fare_not_positive") for part in FARE_PARTS],
            ({"trip_miles": None}, "bad_distance"),
            ({"dropoff_datetime": None}, "bad_duration"),
        ]
        for override, rule in cases:
            with self.subTest(override=override):
                self.assert_rule(rule, removed_rows=[override], kept_rows=[])

    def test_unused_columns_never_remove_a_trip(self):
        # Missing request time only makes the wait invalid (see WaitTests).
        unused = [
            "request_datetime",
            "on_scene_datetime",
            "tips",
            "driver_pay",
            "trip_time",
            "dispatching_base_num",
            "originating_base_num",
        ]
        kept, removed = run_clean(*[{column: None} for column in unused])

        self.assertEqual(len(kept), len(unused))
        self.assertEqual(sum(removed.values()), 0)


class WaitTests(SimpleTestCase):
    """Wait validity is tracked on kept trips and never removes a trip."""

    def test_wait_boundaries(self):
        # VALID_TRIP picks up at 08:00:00.
        kept, removed = run_clean(
            {"request_datetime": "2026-03-10 08:00:01"},  # -1 s
            {"request_datetime": "2026-03-10 08:00:00"},  # 0 s
            {"request_datetime": "2026-03-10 07:00:00"},  # 3,600 s
            {"request_datetime": "2026-03-10 06:59:59"},  # 3,601 s
            {"request_datetime": None},  # missing
        )

        self.assertEqual(sum(removed.values()), 0)
        self.assertEqual(kept["wait_valid"].tolist(), [False, True, True, False, False])
        self.assertEqual(kept["wait_s"].tolist(), [0, 0, 3600, 0, 0])

    def test_wait_in_whole_seconds(self):
        kept, _ = run_clean({"request_datetime": "2026-03-10 07:55:30"})

        self.assertEqual(kept["wait_s"].tolist(), [270])
        self.assertEqual(kept["wait_valid"].tolist(), [True])

    def test_on_scene_time_is_not_used(self):
        kept, _ = run_clean(
            {"on_scene_datetime": "2026-03-10 07:00:00"},
            {"on_scene_datetime": None},
        )

        self.assertEqual(kept["wait_s"].tolist(), [300, 300])


class RuleOrderTests(SimpleTestCase):
    def test_report_keys_follow_rule_order(self):
        _, removed = run_clean({})

        self.assertEqual(
            list(removed),
            [
                "pickup_outside_month",
                "other_provider",
                "shared_ride",
                "unknown_zone",
                "fare_not_positive",
                "fare_over_max",
                "bad_distance",
                "bad_duration",
            ],
        )

    def test_trip_breaking_several_rules_is_counted_once_under_the_first(self):
        _, removed = run_clean(
            {"hvfhs_license_num": "HV0004", "shared_request_flag": "Y"},
            {"shared_match_flag": "Y", "DOLocationID": 265, "trip_miles": 0.0},
            {"pickup_datetime": "2026-04-02 08:00:00", "hvfhs_license_num": "HV0002"},
            {**fare(0.0), "trip_miles": 0.0, "dropoff_datetime": None},
        )

        self.assertEqual(removed["other_provider"], 1)
        self.assertEqual(removed["shared_ride"], 1)
        self.assertEqual(removed["pickup_outside_month"], 1)
        self.assertEqual(removed["fare_not_positive"], 1)
        self.assertEqual(sum(removed.values()), 4)

    def test_read_equals_kept_plus_removed(self):
        trips = make_trips(
            {},
            {"shared_request_flag": "Y"},
            {"trip_miles": 0.0, "base_passenger_fare": 0.0},
            {"PULocationID": None, "dropoff_datetime": None},
            {"PULocationID": 4, "request_datetime": None},
        )

        kept, removed = clean_trips(trips, MONTH, KNOWN_ZONE_IDS)

        self.assertEqual(len(kept), 2)
        self.assertEqual(len(kept) + sum(removed.values()), len(trips))


class KeptColumnsTests(SimpleTestCase):
    def test_columns_and_types(self):
        kept, _ = run_clean({})

        self.assertEqual(
            list(kept.columns),
            [
                "pickup_zone_id",
                "dropoff_zone_id",
                "day_of_week",
                "hour",
                "duration_s",
                "fare_cents",
                "miles_hundredths",
                "wait_s",
                "wait_valid",
            ],
        )
        self.assertEqual(
            kept.dtypes.astype(str).tolist(),
            ["int16", "int16", "int8", "int8", "int64", "int64", "int64", "int64"]
            + ["bool"],
        )

    def test_zone_ids_are_ints_after_nulls_are_removed(self):
        kept, _ = run_clean({"PULocationID": None}, {"PULocationID": 4})

        self.assertEqual(kept["pickup_zone_id"].tolist(), [4])
        self.assertEqual(str(kept["pickup_zone_id"].dtype), "int16")

    def test_day_of_week_is_monday_zero_and_hour_from_pickup(self):
        kept, _ = run_clean(
            {
                "request_datetime": "2026-03-02 09:55:00",
                "pickup_datetime": "2026-03-02 10:00:00",  # Monday
                "dropoff_datetime": "2026-03-02 10:20:00",
            },
            {
                "request_datetime": "2026-03-08 23:20:00",
                "pickup_datetime": "2026-03-08 23:30:00",  # Sunday
                "dropoff_datetime": "2026-03-09 00:10:00",
            },
        )

        self.assertEqual(kept["day_of_week"].tolist(), [0, 6])
        self.assertEqual(kept["hour"].tolist(), [10, 23])

    def test_duration_in_whole_seconds(self):
        kept, _ = run_clean({"dropoff_datetime": "2026-03-10 08:15:30"})

        self.assertEqual(kept["duration_s"].tolist(), [930])

    def test_fare_cents_is_the_seven_parts_without_tips(self):
        kept, _ = run_clean(
            {},  # 26.53, see VALID_TRIP
            {
                "base_passenger_fare": 30.1,
                "tolls": 6.94,
                "bcf": 0.9,
                "sales_tax": 2.75,
                "congestion_surcharge": 2.75,
                "airport_fee": 2.5,
                "cbd_congestion_fee": 1.5,
                "tips": 8.0,
            },
        )

        self.assertEqual(kept["fare_cents"].tolist(), [2653, 4744])

    def test_fare_cents_has_no_float_noise(self):
        # 0.1 + 0.2 is 0.30000000000000004 in floats.
        kept, _ = run_clean(fare(0.1, tolls=0.2))

        self.assertEqual(kept["fare_cents"].tolist(), [30])

    def test_miles_in_integer_hundredths(self):
        kept, _ = run_clean(
            {"trip_miles": 2.5}, {"trip_miles": 0.01}, {"trip_miles": 13.37}
        )

        self.assertEqual(kept["miles_hundredths"].tolist(), [250, 1, 1337])

    def test_no_trip_kept(self):
        kept, removed = run_clean({"trip_miles": 0.0})

        self.assertEqual(len(kept), 0)
        self.assertEqual(removed["bad_distance"], 1)


class AddRemovedTests(SimpleTestCase):
    def test_adds_rule_by_rule(self):
        first = {key: 1 for key, _ in RULES}
        second = {key: 0 for key, _ in RULES}
        second["shared_ride"] = 5

        total = add_removed(first, second)

        self.assertEqual(list(total), [key for key, _ in RULES])
        self.assertEqual(total["shared_ride"], 6)
        self.assertEqual(total["bad_duration"], 1)

    def test_nothing_gives_zeros(self):
        self.assertEqual(add_removed(), {key: 0 for key, _ in RULES})


class BatchTests(SimpleTestCase):
    """Cleaning a file in several batches gives the same result as one."""

    TRIPS = [
        {},
        {"hvfhs_license_num": "HV0005", "PULocationID": 4},
        {"shared_request_flag": "Y"},
        {"DOLocationID": 265},
        {"hvfhs_license_num": "HV0004"},
        fare(0.0),
        fare(600.0),
        {"trip_miles": 0.0},
        {"dropoff_datetime": "2026-03-10 08:00:30"},
        {"pickup_datetime": "2026-04-01 00:00:00"},
        {"request_datetime": None, "PULocationID": 7},
        {"request_datetime": "2026-03-10 08:00:05", "DOLocationID": 4},
        {"pickup_datetime": "2026-03-31 23:59:00", "dropoff_datetime": None},
    ]

    def clean_file(self, path, batch_size):
        batches = list(read_batches(path, batch_size=batch_size))
        cleaned = [clean_trips(batch, MONTH, KNOWN_ZONE_IDS) for batch in batches]
        kept = pd.concat([k for k, _ in cleaned], ignore_index=True)
        return len(batches), kept, add_removed(*[r for _, r in cleaned])

    def test_several_batches_equal_one_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fhvhv.parquet"
            write_trips(path, *self.TRIPS)

            n_one, kept_one, removed_one = self.clean_file(path, batch_size=100)
            n_many, kept_many, removed_many = self.clean_file(path, batch_size=3)

        self.assertEqual((n_one, n_many), (1, 5))
        pd.testing.assert_frame_equal(kept_many, kept_one)
        self.assertEqual(removed_many, removed_one)
        self.assertEqual(len(kept_one), 4)
        self.assertEqual(kept_one["wait_valid"].tolist(), [True, True, False, False])
        self.assertEqual(
            removed_one,
            {
                "pickup_outside_month": 1,
                "other_provider": 1,
                "shared_ride": 1,
                "unknown_zone": 1,
                "fare_not_positive": 1,
                "fare_over_max": 1,
                "bad_distance": 1,
                "bad_duration": 2,
            },
        )
