"""US41 #115: the cleaning limits are one editable record per import,
start with the limits from before US41, are validated, and are what the
cleaning code compares."""

import importlib
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from reports.models import MAX_FARE
from zones.importer import clean as taxi_clean
from zones.importer import rules
from zones.importer.rideshare import clean as rideshare_clean
from zones.models import (
    FARE_CAP,
    FARE_NOT_POSITIVE,
    FARE_OVER_CAP,
    NEGATIVE,
    STARTING_VALUES,
    WAIT_REQUIRED,
    CleaningRules,
    ImportRun,
)
from zones.tests import importer_helpers as taxi_trips
from zones.tests import rideshare_helpers as rideshare_trips

TAXI = ImportRun.Dataset.TAXI
RIDESHARE = ImportRun.Dataset.RIDESHARE
MONTH = "2026-03"

# The rule labels before US41, copied here so a change to them shows up.
OLD_TAXI_LABELS = (
    ("pickup_outside_month", "Pickup outside the file's month"),
    ("voided", "Voided trip (payment_type 6)"),
    ("unknown_zone", "Unknown pickup or dropoff zone"),
    ("fare_not_positive", "Fare <= 0 or fare before tip <= 0"),
    ("fare_over_max", "Fare before tip > $500"),
    ("bad_distance", "Distance <= 0 or > 100 miles"),
    ("bad_duration", "Duration < 1 or > 180 minutes"),
)
OLD_RIDESHARE_LABELS = (
    ("pickup_outside_month", "Pickup outside the file's month"),
    ("other_provider", "Provider not Uber or Lyft"),
    ("shared_ride", "Shared ride (requested or matched)"),
    ("unknown_zone", "Unknown pickup or dropoff zone"),
    ("fare_not_positive", "Base fare <= 0 or fare before tip <= 0"),
    ("fare_over_max", "Fare before tip > $500"),
    ("bad_distance", "Distance <= 0 or > 100 miles"),
    ("bad_duration", "Duration < 1 or > 180 minutes"),
)


def rules_with(dataset, **changes):
    return CleaningRules(dataset=dataset, **{**STARTING_VALUES[dataset], **changes})


class StartingValuesTests(TestCase):
    def test_the_migration_makes_one_record_per_import(self):
        self.assertEqual(
            list(CleaningRules.objects.values_list("dataset", flat=True)),
            ["rideshare", "taxi"],
        )

    def test_records_start_with_the_limits_from_before_us41(self):
        self.assertEqual(
            rules.current_limits(TAXI),
            taxi_clean.Limits(
                max_fare_cents=50_000,
                min_distance_mi=0,
                max_distance_mi=100,
                min_duration_s=60,
                max_duration_s=10_800,
            ),
        )
        self.assertEqual(
            rules.current_limits(RIDESHARE),
            rideshare_clean.RideshareLimits(
                max_fare_cents=50_000,
                min_distance_mi=0,
                max_distance_mi=100,
                min_duration_s=60,
                max_duration_s=10_800,
                min_wait_s=0,
                max_wait_s=3_600,
            ),
        )

    def test_starting_values_are_the_code_defaults(self):
        for dataset, default in (
            (TAXI, taxi_clean.DEFAULT_LIMITS),
            (RIDESHARE, rideshare_clean.DEFAULT_LIMITS),
        ):
            with self.subTest(dataset):
                self.assertEqual(rules.current_limits(dataset), default)

    def test_the_migration_and_the_model_start_with_the_same_values(self):
        migration = importlib.import_module("zones.migrations.0006_cleaning_rules")
        for dataset, values in migration.STARTING_VALUES.items():
            with self.subTest(dataset):
                expected = dict(STARTING_VALUES[dataset])
                if dataset == TAXI:
                    self.assertIsNone(expected.pop("min_wait_min"))
                    self.assertIsNone(expected.pop("max_wait_min"))
                self.assertEqual(values, expected)

    def test_a_missing_record_is_made_again_with_the_starting_values(self):
        CleaningRules.objects.filter(dataset=RIDESHARE).delete()

        self.assertEqual(
            rules.current_limits(RIDESHARE), rideshare_clean.DEFAULT_LIMITS
        )
        self.assertEqual(CleaningRules.objects.filter(dataset=RIDESHARE).count(), 1)

    def test_the_fare_cap_is_the_fare_report_limit(self):
        self.assertEqual(FARE_CAP, MAX_FARE)

    def test_labels_at_the_starting_values_are_the_old_labels(self):
        self.assertEqual(taxi_clean.RULES, OLD_TAXI_LABELS)
        self.assertEqual(rideshare_clean.RULES, OLD_RIDESHARE_LABELS)
        self.assertEqual(taxi_clean.rules(rules.current_limits(TAXI)), OLD_TAXI_LABELS)
        self.assertEqual(
            rideshare_clean.rules(rules.current_limits(RIDESHARE)),
            OLD_RIDESHARE_LABELS,
        )

    def test_str(self):
        self.assertEqual(str(CleaningRules.current(TAXI)), "Yellow taxi cleaning rules")


class ValidationTests(SimpleTestCase):
    def test_starting_values_are_valid(self):
        for dataset in (TAXI, RIDESHARE):
            with self.subTest(dataset):
                self.assertIsNone(errors_of_without_db(rules_with(dataset)))

    def test_a_minimum_must_be_below_its_maximum(self):
        cases = (
            (
                {"min_distance_mi": Decimal("5"), "max_distance_mi": Decimal("2")},
                "max_distance_mi",
                "maximum distance must be more than",
            ),
            (
                {"min_distance_mi": Decimal("2"), "max_distance_mi": Decimal("2")},
                "max_distance_mi",
                "maximum distance must be more than",
            ),
            (
                {"min_duration_min": 200},
                "max_duration_min",
                "maximum duration must be more than",
            ),
            (
                {"min_duration_min": 180},
                "max_duration_min",
                "maximum duration must be more than",
            ),
            ({"min_wait_min": 60}, "max_wait_min", "maximum wait must be more than"),
        )
        for changes, field, message in cases:
            with self.subTest(changes):
                errors = errors_of_without_db(rules_with(RIDESHARE, **changes))
                self.assertIn(field, errors)
                self.assertIn(message, errors[field][0])

    def test_negative_values_are_refused(self):
        for field in (
            "min_distance_mi",
            "max_distance_mi",
            "min_duration_min",
            "max_duration_min",
            "min_wait_min",
            "max_wait_min",
        ):
            with self.subTest(field):
                errors = errors_of_without_db(rules_with(RIDESHARE, **{field: -1}))
                self.assertIn(NEGATIVE, errors[field])

    def test_the_maximum_fare_is_above_zero_and_at_most_500(self):
        too_high = errors_of_without_db(rules_with(TAXI, max_fare=Decimal("500.01")))
        self.assertEqual(too_high, {"max_fare": [FARE_OVER_CAP]})
        for fare in (Decimal("0"), Decimal("-5")):
            with self.subTest(fare):
                errors = errors_of_without_db(rules_with(TAXI, max_fare=fare))
                self.assertEqual(errors, {"max_fare": [FARE_NOT_POSITIVE]})
        for fare in (Decimal("500"), Decimal("0.01"), Decimal("450.50")):
            with self.subTest(fare):
                self.assertIsNone(errors_of_without_db(rules_with(TAXI, max_fare=fare)))

    def test_rideshare_needs_both_wait_limits(self):
        errors = errors_of_without_db(rules_with(RIDESHARE, max_wait_min=None))
        self.assertEqual(errors, {"max_wait_min": [WAIT_REQUIRED]})
        errors = errors_of_without_db(
            rules_with(RIDESHARE, min_wait_min=None, max_wait_min=None)
        )
        self.assertEqual(
            errors,
            {"min_wait_min": [WAIT_REQUIRED], "max_wait_min": [WAIT_REQUIRED]},
        )

    def test_taxi_has_no_wait_limits(self):
        record = rules_with(TAXI, min_wait_min=3, max_wait_min=9)
        self.assertIsNone(errors_of_without_db(record))
        self.assertEqual((record.min_wait_min, record.max_wait_min), (None, None))


def errors_of_without_db(record):
    """full_clean without the database checks (unique dataset and the
    check constraints), which DatabaseConstraintTests covers."""
    try:
        record.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        return error.message_dict
    return None


class DatabaseConstraintTests(TestCase):
    """The database refuses bad limits too, even without the admin."""

    def assert_refused(self, dataset, **changes):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CleaningRules.objects.filter(dataset=dataset).update(**changes)

    def test_bad_limits_are_refused_by_the_database(self):
        self.assert_refused(TAXI, max_fare=Decimal("600"))
        self.assert_refused(TAXI, max_fare=Decimal("0"))
        self.assert_refused(TAXI, min_distance_mi=Decimal("-1"))
        self.assert_refused(TAXI, min_distance_mi=Decimal("100"))
        self.assert_refused(TAXI, min_duration_min=-1)
        self.assert_refused(TAXI, max_duration_min=1)
        self.assert_refused(TAXI, min_wait_min=0, max_wait_min=60)
        self.assert_refused(RIDESHARE, max_wait_min=None)
        self.assert_refused(RIDESHARE, min_wait_min=60)

    def test_one_record_per_import(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CleaningRules.objects.create(**{"dataset": TAXI, **STARTING_VALUES[TAXI]})


class LimitsTests(SimpleTestCase):
    def test_a_record_becomes_the_units_the_rules_compare(self):
        record = rules_with(
            RIDESHARE,
            max_fare=Decimal("450.50"),
            min_distance_mi=Decimal("0.25"),
            max_distance_mi=Decimal("50.00"),
            min_duration_min=2,
            max_duration_min=120,
            min_wait_min=1,
            max_wait_min=45,
        )
        self.assertEqual(
            rules.limits_from_rules(record),
            rideshare_clean.RideshareLimits(
                max_fare_cents=45_050,
                min_distance_mi=0.25,
                max_distance_mi=50,
                min_duration_s=120,
                max_duration_s=7_200,
                min_wait_s=60,
                max_wait_s=2_700,
            ),
        )

    def test_labels_show_the_limits(self):
        limits = taxi_clean.Limits(
            max_fare_cents=45_050,
            min_distance_mi=0.25,
            max_distance_mi=50,
            min_duration_s=120,
            max_duration_s=7_200,
        )
        labels = dict(taxi_clean.rules(limits))
        self.assertEqual(labels["fare_over_max"], "Fare before tip > $450.50")
        self.assertEqual(labels["bad_distance"], "Distance <= 0.25 or > 50 miles")
        self.assertEqual(labels["bad_duration"], "Duration < 2 or > 120 minutes")
        self.assertEqual(
            dict(rideshare_clean.rules(limits))["fare_over_max"],
            "Fare before tip > $450.50",
        )

    def test_saved_limits_come_back_the_same(self):
        for dataset, limits in (
            (TAXI, taxi_clean.Limits(max_fare_cents=40_000, min_distance_mi=0.5)),
            (RIDESHARE, rideshare_clean.RideshareLimits(max_wait_s=1_800)),
        ):
            with self.subTest(dataset):
                saved = rules.saved_limits(limits)
                self.assertEqual(rules.limits_from_saved(dataset, saved), limits)

    def test_saved_limits_use_the_us40_names(self):
        self.assertEqual(
            rules.saved_limits(rideshare_clean.DEFAULT_LIMITS),
            {
                "MAX_FARE_CENTS": 50_000,
                "MIN_DISTANCE_MI": 0,
                "MAX_DISTANCE_MI": 100,
                "MIN_DURATION_S": 60,
                "MAX_DURATION_S": 10_800,
                "MIN_WAIT_S": 0,
                "MAX_WAIT_S": 3_600,
            },
        )

    def test_a_run_from_before_us41_reads_with_the_starting_values(self):
        us40_run = {
            "MAX_FARE_CENTS": 50_000,
            "MAX_DISTANCE_MI": 100,
            "MIN_DURATION_S": 60,
            "MAX_DURATION_S": 10_800,
            "UNKNOWN_ZONE_IDS": [264, 265],
            "VOIDED_PAYMENT_TYPE": 6,
        }
        self.assertEqual(
            rules.limits_from_saved(TAXI, us40_run), taxi_clean.DEFAULT_LIMITS
        )


class TaxiCleaningWithLimitsTests(SimpleTestCase):
    """VALID_TRIP: fare before tip $19.50, 2.5 miles, 15 minutes."""

    def removed(self, limits, *overrides):
        trips = taxi_trips.make_trips(*overrides)
        kept, removed = taxi_clean.clean_trips(
            trips, MONTH, taxi_trips.KNOWN_ZONE_IDS, limits
        )
        return len(kept), {key: n for key, n in removed.items() if n}

    def test_the_rules_compare_the_given_limits(self):
        limits = taxi_clean.Limits(
            max_fare_cents=1_900,
            min_distance_mi=2.5,
            max_distance_mi=3,
            min_duration_s=16 * 60,
            max_duration_s=20 * 60,
        )
        cases = (
            ({}, {"fare_over_max": 1}),
            ({"tip_amount": 3.5}, {"bad_distance": 1}),  # $19.00, 2.5 miles
            ({"tip_amount": 3.5, "trip_distance": 3.5}, {"bad_distance": 1}),
            ({"tip_amount": 3.5, "trip_distance": 2.6}, {"bad_duration": 1}),
            (
                {
                    "tip_amount": 3.5,
                    "trip_distance": 2.6,
                    "dropoff_at": "2026-03-10 08:21:00",
                },
                {"bad_duration": 1},
            ),
        )
        for override, expected in cases:
            with self.subTest(override):
                self.assertEqual(self.removed(limits, override), (0, expected))

    def test_trips_at_the_limits_are_kept(self):
        limits = taxi_clean.Limits(
            max_fare_cents=1_950,
            min_distance_mi=2.4,
            max_distance_mi=2.5,
            min_duration_s=15 * 60,
            max_duration_s=15 * 60,
        )
        self.assertEqual(self.removed(limits, {}), (1, {}))

    def test_default_limits_are_the_starting_values(self):
        self.assertEqual(
            self.removed(taxi_clean.DEFAULT_LIMITS, {"trip_distance": 0.0}),
            (0, {"bad_distance": 1}),
        )
        self.assertEqual(
            self.removed(taxi_clean.DEFAULT_LIMITS, {"trip_distance": 0.01}),
            (1, {}),
        )


class RideshareCleaningWithLimitsTests(SimpleTestCase):
    """VALID_TRIP: fare before tip $26.53, 2.5 miles, 15 minutes, a
    5-minute wait."""

    def clean(self, limits, *overrides):
        trips = rideshare_trips.make_trips(*overrides)
        return rideshare_clean.clean_trips(
            trips, MONTH, taxi_trips.KNOWN_ZONE_IDS, limits
        )

    def test_the_rules_compare_the_given_limits(self):
        limits = rideshare_clean.RideshareLimits(
            max_fare_cents=2_600, min_distance_mi=3, min_duration_s=20 * 60
        )
        for override, expected in (
            ({}, "fare_over_max"),
            ({"base_passenger_fare": 19.0}, "bad_distance"),
            ({"base_passenger_fare": 19.0, "trip_miles": 3.5}, "bad_duration"),
        ):
            with self.subTest(override):
                kept, removed = self.clean(limits, override)
                self.assertEqual(len(kept), 0)
                self.assertEqual({k for k, n in removed.items() if n}, {expected})

    def test_the_wait_limits_decide_the_wait_average(self):
        limits = rideshare_clean.RideshareLimits(min_wait_s=6 * 60, max_wait_s=600)
        kept, _ = self.clean(
            limits,
            {},  # 5-minute wait: below the minimum
            {"request_datetime": "2026-03-10 07:52:00"},  # 8 minutes
            {"request_datetime": "2026-03-10 07:49:00"},  # 11 minutes
        )
        self.assertEqual(list(kept["wait_valid"]), [False, True, False])
        self.assertEqual(list(kept["wait_s"]), [0, 480, 0])
