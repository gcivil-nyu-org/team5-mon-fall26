import re

import pandas as pd
from django.test import SimpleTestCase

from zones.importer.clean import RULES
from zones.importer.report import MonthReport, format_report, total_report


def removed(**counts):
    return {key: counts.get(key, 0) for key, _ in RULES}


MARCH = MonthReport("2026-03", 1000, removed(bad_distance=40, voided=3), 957)
APRIL = MonthReport("2026-04", 2000, removed(bad_distance=60, unknown_zone=10), 1930)
ZONE_STATS = pd.DataFrame({"trip_count": [4, 5, 1, 300]})
ROUTE_STATS = pd.DataFrame({"trip_count": [1, 2, 5, 6, 4]})


def number_after(label, block):
    """The first number on the line that starts with label."""
    line = next(line.strip() for line in block.splitlines() if line.strip().startswith(label))
    rest = line[len(label):]
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
