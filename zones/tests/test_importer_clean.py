import pandas as pd
from django.test import SimpleTestCase

from zones.importer.clean import RULES, clean_trips, month_bounds
from zones.tests.importer_helpers import KNOWN_ZONE_IDS, make_trips

MONTH = "2026-03"


def run_clean(*overrides):
    return clean_trips(make_trips(*overrides), MONTH, KNOWN_ZONE_IDS)


class MonthBoundsTests(SimpleTestCase):
    def test_start_and_exclusive_end(self):
        self.assertEqual(
            month_bounds("2026-03"),
            (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-04-01")),
        )

    def test_december_ends_in_next_year(self):
        self.assertEqual(month_bounds("2026-12")[1], pd.Timestamp("2027-01-01"))


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
                    "pickup_at": "2026-02-28 23:59:59",
                    "dropoff_at": "2026-03-01 00:15:00",
                },
                {
                    "pickup_at": "2026-04-01 00:00:00",
                    "dropoff_at": "2026-04-01 00:15:00",
                },
            ],
            kept_rows=[
                {
                    "pickup_at": "2026-03-01 00:00:00",
                    "dropoff_at": "2026-03-01 00:15:00",
                },
                {
                    "pickup_at": "2026-03-31 23:59:59",
                    "dropoff_at": "2026-04-01 00:14:59",
                },
            ],
        )

    def test_voided(self):
        # payment_type 0 is a Flex Fare trip and is kept.
        self.assert_rule(
            "voided",
            removed_rows=[{"payment_type": 6}],
            kept_rows=[{"payment_type": 0}, {"payment_type": 2}],
        )

    def test_unknown_zone(self):
        self.assert_rule(
            "unknown_zone",
            removed_rows=[
                {"pickup_zone_id": None},
                {"dropoff_zone_id": None},
                {"pickup_zone_id": 264},
                {"dropoff_zone_id": 264},
                {"pickup_zone_id": 265},
                {"dropoff_zone_id": 265},
                {"pickup_zone_id": 0},  # not in the lookup
                {"dropoff_zone_id": 266},  # not in the lookup
            ],
            kept_rows=[{"pickup_zone_id": 1, "dropoff_zone_id": 263}],
        )

    def test_fare_not_positive(self):
        self.assert_rule(
            "fare_not_positive",
            removed_rows=[
                {"fare_amount": 0.0},
                {"fare_amount": -5.0},
                {"total_amount": 3.0, "tip_amount": 3.0},  # fare before tip 0
                {"total_amount": 2.0, "tip_amount": 3.0},  # fare before tip < 0
            ],
            kept_rows=[{"fare_amount": 0.01, "total_amount": 0.01, "tip_amount": 0.0}],
        )

    def test_fare_over_max(self):
        self.assert_rule(
            "fare_over_max",
            removed_rows=[
                {"total_amount": 500.01, "tip_amount": 0.0},
                {"total_amount": 650.0, "tip_amount": 100.0},
            ],
            kept_rows=[
                {"total_amount": 500.0, "tip_amount": 0.0},
                {"total_amount": 600.0, "tip_amount": 150.0},  # the tip is taken out
            ],
        )

    def test_bad_distance(self):
        self.assert_rule(
            "bad_distance",
            removed_rows=[
                {"trip_distance": 0.0},
                {"trip_distance": -1.0},
                {"trip_distance": 100.01},
            ],
            kept_rows=[{"trip_distance": 0.01}, {"trip_distance": 100.0}],
        )

    def test_bad_duration(self):
        # VALID_TRIP picks up at 08:00:00.
        self.assert_rule(
            "bad_duration",
            removed_rows=[
                {"dropoff_at": "2026-03-10 08:00:59"},
                {"dropoff_at": "2026-03-10 11:00:01"},
                {"dropoff_at": "2026-03-10 08:00:00"},  # zero duration
                {"dropoff_at": "2026-03-10 07:59:00"},  # dropoff before pickup
            ],
            kept_rows=[
                {"dropoff_at": "2026-03-10 08:01:00"},
                {"dropoff_at": "2026-03-10 11:00:00"},
            ],
        )

    def test_missing_values_are_removed_by_their_rule(self):
        cases = [
            ({"pickup_at": None}, "pickup_outside_month"),
            ({"payment_type": None}, None),  # unknown payment type is kept
            ({"fare_amount": None}, "fare_not_positive"),
            ({"total_amount": None}, "fare_not_positive"),
            ({"tip_amount": None}, "fare_not_positive"),
            ({"trip_distance": None}, "bad_distance"),
            ({"dropoff_at": None}, "bad_duration"),
        ]
        for override, rule in cases:
            with self.subTest(override=override):
                if rule is None:
                    self.assert_rule("voided", removed_rows=[], kept_rows=[override])
                else:
                    self.assert_rule(rule, removed_rows=[override], kept_rows=[])


class RuleOrderTests(SimpleTestCase):
    def test_report_keys_follow_rule_order(self):
        _, removed = run_clean({})

        self.assertEqual(
            list(removed),
            [
                "pickup_outside_month",
                "voided",
                "unknown_zone",
                "fare_not_positive",
                "fare_over_max",
                "bad_distance",
                "bad_duration",
            ],
        )

    def test_trip_breaking_several_rules_is_counted_once_under_the_first(self):
        _, removed = run_clean(
            {"payment_type": 6, "fare_amount": 0.0, "trip_distance": 0.0},
            {"pickup_at": "2026-04-02 08:00:00", "pickup_zone_id": 264},
            {"trip_distance": 0.0, "dropoff_at": "2026-03-10 08:00:10"},
        )

        self.assertEqual(removed["voided"], 1)
        self.assertEqual(removed["pickup_outside_month"], 1)
        self.assertEqual(removed["bad_distance"], 1)
        self.assertEqual(sum(removed.values()), 3)

    def test_read_equals_kept_plus_removed(self):
        trips = make_trips(
            {},
            {"payment_type": 6},
            {"trip_distance": 0.0, "fare_amount": 0.0},
            {"pickup_zone_id": None, "dropoff_at": None},
            {"pickup_zone_id": 4},
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
            ],
        )
        self.assertEqual(
            kept.dtypes.astype(str).tolist(),
            ["int16", "int16", "int8", "int8", "int64", "int64"],
        )

    def test_zone_ids_are_ints_after_nulls_are_removed(self):
        kept, _ = run_clean({"pickup_zone_id": None}, {"pickup_zone_id": 4})

        self.assertEqual(kept["pickup_zone_id"].tolist(), [4])
        self.assertEqual(str(kept["pickup_zone_id"].dtype), "int16")

    def test_day_of_week_is_monday_zero(self):
        kept, _ = run_clean(
            {
                "pickup_at": "2026-03-02 10:00:00",
                "dropoff_at": "2026-03-02 10:20:00",
            },  # Monday
            {
                "pickup_at": "2026-03-08 10:00:00",
                "dropoff_at": "2026-03-08 10:20:00",
            },  # Sunday
        )

        self.assertEqual(kept["day_of_week"].tolist(), [0, 6])

    def test_hour_is_the_pickup_hour_as_recorded(self):
        kept, _ = run_clean(
            {"pickup_at": "2026-03-10 23:30:00", "dropoff_at": "2026-03-11 00:10:00"}
        )

        self.assertEqual(kept["hour"].tolist(), [23])
        self.assertEqual(kept["day_of_week"].tolist(), [1])  # Tuesday, from pickup

    def test_duration_in_whole_seconds(self):
        kept, _ = run_clean({"dropoff_at": "2026-03-10 08:15:30"})

        self.assertEqual(kept["duration_s"].tolist(), [930])

    def test_fare_cents_is_fare_before_tip(self):
        # 25.30 - 3.10 is 22.200000000000003 in floats.
        kept, _ = run_clean({"total_amount": 25.30, "tip_amount": 3.10})

        self.assertEqual(kept["fare_cents"].tolist(), [2220])
