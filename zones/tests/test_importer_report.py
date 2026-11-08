import re

import pandas as pd
from django.conf import settings
from django.test import SimpleTestCase

from zones.importer.clean import RULES
from zones.importer.report import (
    REPORT_MIN_TRIPS,
    WAITS_LABEL,
    MonthReport,
    format_report,
    total_report,
)
from zones.importer.rideshare.clean import RULES as RIDESHARE_RULES


def removed(**counts):
    return {key: counts.get(key, 0) for key, _ in RULES}


def rideshare_removed(**counts):
    return {key: counts.get(key, 0) for key, _ in RIDESHARE_RULES}


MARCH = MonthReport("2026-03", 1000, removed(bad_distance=40, voided=3), 957)
APRIL = MonthReport("2026-04", 2000, removed(bad_distance=60, unknown_zone=10), 1930)
ZONE_STATS = pd.DataFrame({"trip_count": [4, 5, 1, 300]})
ROUTE_STATS = pd.DataFrame({"trip_count": [1, 2, 5, 6, 4]})


def number_after(label, block):
    """The first number on the line that starts with label."""
    line = next(
        line.strip() for line in block.splitlines() if line.strip().startswith(label)
    )
    rest = line[len(label) :]
    return int(re.search(r"(\d[\d,]*)\s*(\(|$)", rest).group(1).replace(",", ""))


class MonthReportTests(SimpleTestCase):
    def test_rows_removed(self):
        self.assertEqual(MARCH.rows_removed, 43)

    def test_total_is_the_sum_of_the_months(self):
        total = total_report([MARCH, APRIL])

        self.assertEqual(total.rows_read, 3000)
        self.assertEqual(total.rows_kept, 2887)
        self.assertEqual(total.removed["bad_distance"], 100)
        self.assertEqual(total.removed["voided"], 3)
        self.assertEqual(total.removed["unknown_zone"], 10)
        self.assertEqual(total.rows_removed, 113)


class FormatReportTests(SimpleTestCase):
    def setUp(self):
        self.report = format_report([MARCH, APRIL], ZONE_STATS, ROUTE_STATS)

    def block(self, title):
        blocks = self.report.split("\n\n")
        return next(b for b in blocks if b.splitlines()[0].startswith(title))

    def test_starts_with_the_months_loaded(self):
        self.assertEqual(self.report.splitlines()[0], "Months loaded: 2026-03, 2026-04")

    def test_month_block_has_read_removed_per_rule_and_kept(self):
        march = self.block("2026-03")

        self.assertEqual(number_after("Rows read", march), 1000)
        self.assertEqual(number_after("Rows removed", march), 43)
        self.assertEqual(number_after("Rows kept", march), 957)
        for key, label in RULES:
            self.assertIn(label, march)
        self.assertEqual(number_after(dict(RULES)["bad_distance"], march), 40)
        self.assertEqual(number_after(dict(RULES)["voided"], march), 3)
        self.assertEqual(number_after(dict(RULES)["fare_over_max"], march), 0)

    def test_rules_are_listed_in_rule_order(self):
        march = self.block("2026-03")
        positions = [march.index(label) for _, label in RULES]

        self.assertEqual(positions, sorted(positions))

    def test_removed_share_is_shown(self):
        self.assertIn("4.30%", self.block("2026-03"))

    def test_total_block(self):
        total = self.block("Total")

        self.assertEqual(number_after("Rows read", total), 3000)
        self.assertEqual(number_after("Rows removed", total), 113)
        self.assertEqual(number_after("Rows kept", total), 2887)

    def test_large_numbers_have_thousands_separators(self):
        report = format_report(
            [MonthReport("2026-03", 3952451, removed(bad_distance=224134), 3728317)],
            ZONE_STATS,
            ROUTE_STATS,
        )

        self.assertIn("3,952,451", report)

    def test_cells_and_cells_under_five(self):
        cells = self.block("Zone cells")

        self.assertEqual(number_after("Zone cells", cells), 4)
        self.assertEqual(number_after("Route cells", cells), 5)
        # trip_count 4 and 1 are under 5; 5 is not.
        self.assertIn("2 with fewer than 5 trips", cells.splitlines()[0])
        self.assertIn("3 with fewer than 5 trips", cells.splitlines()[1])


class RideshareReportTests(SimpleTestCase):
    """The same layout with the rideshare rules and the waits line."""

    def setUp(self):
        self.march = MonthReport(
            "2026-03",
            1000,
            rideshare_removed(shared_ride=30, fare_not_positive=7),
            963,
            waits_left_out=12,
        )
        self.april = MonthReport(
            "2026-04", 500, rideshare_removed(unknown_zone=20), 480, waits_left_out=3
        )
        self.report = format_report(
            [self.march, self.april], ZONE_STATS, ROUTE_STATS, RIDESHARE_RULES
        )

    def block(self, title):
        return next(b for b in self.report.split("\n\n") if b.startswith(title))

    def test_lists_the_rideshare_rules_in_order(self):
        march = self.block("2026-03")
        positions = [march.index(label) for _, label in RIDESHARE_RULES]

        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("Voided", march)
        self.assertEqual(number_after(dict(RIDESHARE_RULES)["shared_ride"], march), 30)
        self.assertEqual(number_after("Rows removed", march), 37)

    def test_waits_left_out_per_month_and_in_total(self):
        march = self.block("2026-03")

        self.assertEqual(number_after(WAITS_LABEL, march), 12)
        self.assertIn("(1.25% of kept)", march)  # 12 / 963
        total = self.block("Total")
        self.assertEqual(number_after(WAITS_LABEL, total), 15)
        self.assertEqual(number_after("Rows kept", total), 1443)

    def test_numbers_line_up_under_the_longest_label(self):
        march = self.block("2026-03").splitlines()[1:]
        ends = {len(line.split("  (")[0]) for line in march}

        self.assertEqual(len(ends), 1)

    def test_taxi_report_has_no_waits_line(self):
        report = format_report([MARCH, APRIL], ZONE_STATS, ROUTE_STATS)

        self.assertNotIn(WAITS_LABEL, report)
        self.assertIsNone(total_report([MARCH, APRIL]).waits_left_out)


class ReportMinTripsTests(SimpleTestCase):
    def test_uses_the_api_minimum_trip_count(self):
        self.assertEqual(REPORT_MIN_TRIPS, settings.MIN_TRIP_COUNT)
