"""US41 #115: the next import uses the limits in the admin, prints them in
its report and saves them in its import history (US40). With the starting
values the imports give the same results as before US41."""

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from zones.importer import pipeline
from zones.importer.rideshare import pipeline as rideshare_pipeline
from zones.models import CleaningRules, ImportRun, RouteHourStats
from zones.tests import test_import_rideshare_command as rideshare_cmd
from zones.tests import test_import_trips_command as taxi_cmd
from zones.tests.test_import_history import ImportFiles
from zones.tests.test_import_rideshare_command import block, number_after

TAXI = ImportRun.Dataset.TAXI
RIDESHARE = ImportRun.Dataset.RIDESHARE


def set_rules(dataset, **values):
    CleaningRules.objects.filter(dataset=dataset).update(**values)


class TaxiImportUsesTheRulesTests(ImportFiles, TestCase):
    """taxi_cmd.MARCH: 3 trips of 2.5, 2.5 and 0 miles, all $19.50 and 15
    minutes; 2 kept with the starting values."""

    def test_starting_values_give_the_same_results_as_before(self):
        output = self.taxi("2026-03")

        march = block(output, "2026-03")
        self.assertEqual(number_after("Rows read", march), len(taxi_cmd.MARCH))
        self.assertEqual(number_after("Rows kept", march), 2)
        self.assertEqual(number_after("Distance <= 0 or > 100 miles", march), 1)
        self.assertIn("Fare before tip > $500", march)
        self.assertIn("Duration < 1 or > 180 minutes", march)

    def test_the_next_import_uses_the_new_limits(self):
        set_rules(TAXI, max_fare=Decimal("19.00"))

        output = self.taxi("2026-03")

        march = block(output, "2026-03")
        # The fare rule comes before the distance rule, so the zero-mile
        # trip counts under the fare now.
        self.assertEqual(number_after("Fare before tip > $19", march), 3)
        self.assertEqual(number_after("Distance <= 0 or > 100 miles", march), 0)
        self.assertEqual(number_after("Rows kept", march), 0)
        self.assertEqual(RouteHourStats.objects.count(), 0)

    def test_the_import_history_shows_the_limits_used(self):
        set_rules(
            TAXI,
            max_fare=Decimal("450.50"),
            min_distance_mi=Decimal("0.25"),
            max_duration_min=120,
        )

        output = self.taxi("2026-03")

        run = ImportRun.objects.get()
        self.assertEqual(
            run.cleaning_limits,
            {
                "MAX_FARE_CENTS": 45_050,
                "MIN_DISTANCE_MI": 0.25,
                "MAX_DISTANCE_MI": 100,
                "MIN_DURATION_S": 60,
                "MAX_DURATION_S": 7_200,
                "UNKNOWN_ZONE_IDS": [264, 265],
                "VOIDED_PAYMENT_TYPE": 6,
            },
        )
        self.assertIn("Distance <= 0.25 or > 100 miles", run.report)
        self.assertIn(f"\n{run.report}\n", output)

    def test_a_change_during_an_import_applies_to_the_next_one(self):
        real_run_import = pipeline.run_import

        def edit_while_running(*args, **kwargs):
            set_rules(TAXI, max_fare=Decimal("19.00"))
            return real_run_import(*args, **kwargs)

        with mock.patch(
            "zones.management.commands.import_trips.run_import", edit_while_running
        ):
            first = self.taxi("2026-03")
        second = self.taxi("2026-03")

        self.assertEqual(number_after("Rows kept", block(first, "2026-03")), 2)
        self.assertEqual(number_after("Rows kept", block(second, "2026-03")), 0)
        older, newer = ImportRun.objects.order_by("id")
        self.assertEqual(older.cleaning_limits["MAX_FARE_CENTS"], 50_000)
        self.assertEqual(newer.cleaning_limits["MAX_FARE_CENTS"], 1_900)


class RideshareImportUsesTheRulesTests(ImportFiles, TestCase):
    """rideshare_cmd.MARCH: 5 trips, 3 kept with the starting values, one
    of them with a negative wait (left out of the wait average)."""

    def test_starting_values_give_the_same_results_as_before(self):
        output = self.rideshare("2026-03")

        march = block(output, "2026-03")
        self.assertEqual(number_after("Rows read", march), len(rideshare_cmd.MARCH))
        self.assertEqual(number_after("Rows kept", march), 3)
        self.assertEqual(number_after("Waits left out of the average", march), 1)
        self.assertIn("Fare before tip > $500", march)
        run = ImportRun.objects.get()
        self.assertEqual(
            (run.cleaning_limits["MIN_WAIT_S"], run.cleaning_limits["MAX_WAIT_S"]),
            (0, 3_600),
        )

    def test_the_next_import_uses_the_new_wait_limits(self):
        before = self.rideshare("2026-03")
        waits_before = number_after(
            "Waits left out of the average", block(before, "Total")
        )
        set_rules(RIDESHARE, min_wait_min=59, max_wait_min=60)

        after = self.rideshare("2026-03")

        kept = number_after("Rows kept", block(after, "Total"))
        self.assertEqual(
            number_after("Waits left out of the average", block(after, "Total")), kept
        )
        self.assertGreater(kept, waits_before)
        run = ImportRun.objects.order_by("-id").first()
        self.assertEqual(
            (run.cleaning_limits["MIN_WAIT_S"], run.cleaning_limits["MAX_WAIT_S"]),
            (3_540, 3_600),
        )

    def test_the_next_import_uses_the_new_fare_limit(self):
        set_rules(RIDESHARE, max_fare=Decimal("1.00"))

        output = self.rideshare("2026-03")

        total = block(output, "Total")
        self.assertEqual(number_after("Rows kept", total), 0)
        self.assertGreater(number_after("Fare before tip > $1", total), 0)

    def test_the_pipeline_gets_the_limits(self):
        set_rules(RIDESHARE, max_duration_min=90)
        real = rideshare_pipeline.run_rideshare_import
        seen = {}

        def spy(*args, **kwargs):
            seen["limits"] = kwargs["limits"]
            return real(*args, **kwargs)

        with mock.patch(
            "zones.management.commands.import_rideshare.run_rideshare_import", spy
        ):
            self.rideshare("2026-03")

        self.assertEqual(seen["limits"].max_duration_s, 5_400)


class ImportHistoryLabelsTests(ImportFiles, TestCase):
    """A run's page in the import history labels the removed rows with the
    limits that run used, not today's."""

    def test_run_page_uses_the_runs_own_limits(self):
        set_rules(TAXI, max_fare=Decimal("19.00"))
        self.taxi("2026-03")
        set_rules(TAXI, max_fare=Decimal("400.00"))
        staff = get_user_model().objects.create_superuser(
            "staff@example.com", "staff@example.com", "taxi-route-7319"
        )
        self.client.force_login(staff)

        run = ImportRun.objects.get()
        response = self.client.get(
            reverse("admin:zones_importrun_change", args=[run.pk])
        )
        self.assertContains(response, "Fare before tip &gt; $19")
        self.assertNotContains(response, "Fare before tip &gt; $400")
