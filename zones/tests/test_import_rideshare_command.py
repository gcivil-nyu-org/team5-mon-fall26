import io
import re
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.error import URLError

import pyarrow.parquet as pq
from django.core.management import CommandError, call_command
from django.db.models import Sum
from django.test import TestCase

from zones.importer.rideshare import load as rideshare_load
from zones.importer.rideshare import pipeline
from zones.importer.rideshare.clean import RULES
from zones.importer.rideshare.download import rideshare_file_path
from zones.importer.rideshare.read import read_batches
from zones.models import (
    RideshareRouteHourStats,
    RideshareZoneHourStats,
    RouteHourStats,
    Zone,
    ZoneHourStats,
)
from zones.tests.rideshare_helpers import make_table, write_trips

LABELS = dict(RULES)

# 5 March trips, 3 kept: one shared ride, one drops off outside NYC
# (zone 265). One kept trip has a negative wait, so it is left out of the
# wait average. The two 161 -> 237 trips share a cell (Tuesday 08:00).
MARCH = (
    {},
    {"request_datetime": "2026-03-10 08:02:00", "base_passenger_fare": 30.0},
    {"PULocationID": 4},
    {"shared_request_flag": "Y"},
    {"DOLocationID": 265},
)
# 3 trips in the April file, 2 kept (one picks up in March). Both kept
# trips are Tuesday 18:00, 161 -> 237.
APRIL = (
    {
        "request_datetime": "2026-04-07 17:50:00",
        "pickup_datetime": "2026-04-07 18:00:00",
        "dropoff_datetime": "2026-04-07 18:30:00",
    },
    {
        "request_datetime": "2026-04-07 18:00:00",
        "pickup_datetime": "2026-04-07 18:05:00",
        "dropoff_datetime": "2026-04-07 18:25:00",
    },
    {
        "request_datetime": "2026-03-31 22:55:00",
        "pickup_datetime": "2026-03-31 23:00:00",
        "dropoff_datetime": "2026-03-31 23:20:00",
    },
)


def trip_total(model):
    return model.objects.aggregate(total=Sum("trip_count"))["total"]


def table_rows(model):
    fields = [f.attname for f in model._meta.concrete_fields if f.name != "id"]
    return list(model.objects.order_by(*fields).values_list(*fields))


def rideshare_rows():
    return table_rows(RideshareZoneHourStats), table_rows(RideshareRouteHourStats)


def number_after(label, block):
    """The first number on the line that starts with label."""
    line = next(
        line.strip() for line in block.splitlines() if line.strip().startswith(label)
    )
    return int(re.search(r"(\d[\d,]*)", line[len(label) :]).group(1).replace(",", ""))


def block(output, title):
    """The report block whose first line starts with title (the progress
    lines, such as "2026-03: 5 read", are not blocks)."""
    return next(
        b
        for b in output.split("\n\n")
        if b.splitlines()[0].startswith(title) and ":" not in b.splitlines()[0]
    )


def report_only(output):
    """The report blocks, without the progress lines and the timing."""
    return [b for b in output.split("\n\n") if "Finished in" not in b][1:]


class FakeResponse(io.BytesIO):
    """What urlopen returns, enough for shutil.copyfileobj."""


class ImportRideshareCommandTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        write_trips(rideshare_file_path("2026-03", self.data_dir), *MARCH)
        write_trips(rideshare_file_path("2026-04", self.data_dir), *APRIL)

        # The tests never touch the network.
        patcher = mock.patch(
            "zones.importer.download.urlopen",
            side_effect=URLError("no network in tests"),
        )
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)

    def run_import(self, *months):
        out = StringIO()
        args = []
        for month in months:
            args += ["--month", month]
        call_command(
            "import_rideshare", *args, "--data-dir", str(self.data_dir), stdout=out
        )
        return out.getvalue()

    # Acceptance: one or more months with one command.

    def test_imports_several_months_with_one_command(self):
        self.run_import("2026-03", "2026-04")

        self.assertEqual(Zone.objects.count(), 265)
        self.assertEqual(trip_total(RideshareZoneHourStats), 5)
        self.assertEqual(trip_total(RideshareRouteHourStats), 5)
        self.urlopen.assert_not_called()

        march = RideshareRouteHourStats.objects.get(
            pickup_zone_id=161, dropoff_zone_id=237, day_of_week=1, hour=8
        )
        self.assertEqual(march.trip_count, 2)
        # 26.53 and 36.53: base fare 20 and 30, the same other parts.
        self.assertEqual(march.fare_avg, Decimal("31.53"))
        # Only the first trip's 5-minute wait counts; the other is negative.
        self.assertEqual(march.wait_count, 1)
        self.assertEqual(march.avg_wait_min, 5.0)

        april = RideshareRouteHourStats.objects.get(
            pickup_zone_id=161, dropoff_zone_id=237, day_of_week=1, hour=18
        )
        self.assertEqual(april.trip_count, 2)
        self.assertEqual(april.avg_duration_min, 25.0)  # 30 and 20 minutes
        self.assertEqual(april.avg_wait_min, 7.5)  # 10 and 5 minutes

        self.assertFalse(
            RideshareRouteHourStats.objects.filter(dropoff_zone_id=265).exists()
        )

    def test_batches_give_the_same_rows_and_report_as_one_read(self):
        whole_report = report_only(self.run_import("2026-03", "2026-04"))
        whole = rideshare_rows()

        def one_trip_per_batch(path):
            return read_batches(path, batch_size=1)

        with mock.patch.object(pipeline, "read_batches", one_trip_per_batch):
            output = self.run_import("2026-03", "2026-04")

        self.assertEqual(rideshare_rows(), whole)
        self.assertEqual(report_only(output), whole_report)
        self.assertEqual(number_after("Rows read", block(output, "Total")), 8)

    def test_taxi_tables_are_not_touched(self):
        self.run_import("2026-03", "2026-04")

        self.assertFalse(ZoneHourStats.objects.exists())
        self.assertFalse(RouteHourStats.objects.exists())

    # Acceptance: the report shows rows read, removed by each rule, and kept.

    def test_report_shows_read_removed_per_rule_and_kept(self):
        output = self.run_import("2026-03", "2026-04")

        self.assertIn("Months loaded: 2026-03, 2026-04", output)
        march = block(output, "2026-03")
        self.assertEqual(number_after("Rows read", march), 5)
        self.assertEqual(number_after(LABELS["shared_ride"], march), 1)
        self.assertEqual(number_after(LABELS["unknown_zone"], march), 1)
        self.assertEqual(number_after(LABELS["pickup_outside_month"], march), 0)
        self.assertEqual(number_after("Rows removed", march), 2)
        self.assertEqual(number_after("Rows kept", march), 3)
        self.assertEqual(number_after("Waits left out of the average", march), 1)

        april = block(output, "2026-04")
        self.assertEqual(number_after(LABELS["pickup_outside_month"], april), 1)
        self.assertEqual(number_after("Rows kept", april), 2)
        self.assertEqual(number_after("Waits left out of the average", april), 0)

        total = block(output, "Total (2 months)")
        self.assertEqual(number_after("Rows read", total), 8)
        self.assertEqual(number_after("Rows removed", total), 3)
        self.assertIn("(37.50%)", total)
        self.assertEqual(number_after("Rows kept", total), 5)
        self.assertEqual(number_after("Waits left out of the average", total), 1)

    def test_report_lists_every_rule_in_rule_order(self):
        march = block(self.run_import("2026-03"), "2026-03")

        positions = [march.index(label) for _, label in RULES]
        self.assertEqual(positions, sorted(positions))

    def test_report_counts_cells_and_small_cells(self):
        output = self.run_import("2026-03", "2026-04")

        cells = block(output, "Zone cells")
        # Zone cells: 161 Tue 08 (2 trips), 4 Tue 08 (1), 161 Tue 18 (2).
        self.assertEqual(number_after("Zone cells", cells), 3)
        self.assertIn("(3 with fewer than 5 trips)", cells.splitlines()[0])
        # Route cells: 161->237 Tue 08, 4->237 Tue 08, 161->237 Tue 18.
        self.assertEqual(number_after("Route cells", cells), 3)
        self.assertIn("Zones loaded: 265.", output)
        self.assertRegex(output, r"Finished in \d+ s\.")

    # Acceptance: running twice creates no duplicates.

    def test_running_twice_gives_the_same_rows(self):
        self.run_import("2026-03", "2026-04")
        first = rideshare_rows(), Zone.objects.count()

        self.run_import("2026-03", "2026-04")

        self.assertEqual((rideshare_rows(), Zone.objects.count()), first)
        self.assertEqual(RideshareRouteHourStats.objects.count(), 3)

    def test_fewer_months_replace_all_stats(self):
        self.run_import("2026-03", "2026-04")

        output = self.run_import("2026-04")

        self.assertEqual(trip_total(RideshareZoneHourStats), 2)
        self.assertEqual(trip_total(RideshareRouteHourStats), 2)
        self.assertIn("Months loaded: 2026-04\n", output)
        self.assertIn("Total (1 month)", output)

    # Acceptance: a failed import leaves the old data in place.

    def test_failure_while_writing_keeps_the_old_data(self):
        self.run_import("2026-03")
        before = rideshare_rows()
        real_copy_rows = rideshare_load.copy_rows

        def fail_on_routes(model, columns, rows):
            if model is RideshareRouteHourStats:
                raise RuntimeError("connection lost")
            return real_copy_rows(model, columns, rows)

        with mock.patch.object(rideshare_load, "copy_rows", fail_on_routes):
            with self.assertRaisesMessage(RuntimeError, "connection lost"):
                self.run_import("2026-03", "2026-04")

        self.assertEqual(rideshare_rows(), before)

    def test_bad_file_is_an_error_before_any_trip_is_read(self):
        self.run_import("2026-03")
        before = rideshare_rows()
        write_trips(rideshare_file_path("2026-05", self.data_dir), {}, drop=["tolls"])

        with mock.patch.object(pipeline, "clean_trips") as clean:
            with self.assertRaisesMessage(CommandError, "tolls"):
                self.run_import("2026-03", "2026-05")

        clean.assert_not_called()
        self.assertEqual(rideshare_rows(), before)

    def test_failed_download_is_an_error_and_keeps_the_old_data(self):
        self.run_import("2026-03")
        before = rideshare_rows()

        with mock.patch.object(pipeline, "clean_trips") as clean:
            with self.assertRaisesMessage(CommandError, "Could not download 2026-06"):
                self.run_import("2026-03", "2026-06")

        clean.assert_not_called()
        self.assertEqual(rideshare_rows(), before)
        self.assertFalse(rideshare_file_path("2026-06", self.data_dir).exists())
        self.assertEqual(list(self.data_dir.glob("*.part")), [])

    # Downloading.

    def test_missing_month_is_downloaded_first(self):
        buffer = io.BytesIO()
        may_trip = {
            "request_datetime": "2026-05-12 07:55:00",
            "pickup_datetime": "2026-05-12 08:00:00",
            "dropoff_datetime": "2026-05-12 08:15:00",
        }
        pq.write_table(make_table(may_trip), buffer)
        self.urlopen.side_effect = None
        self.urlopen.return_value = FakeResponse(buffer.getvalue())

        output = self.run_import("2026-03", "2026-05")

        self.urlopen.assert_called_once()
        request = self.urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://d37ci6vzurychx.cloudfront.net/trip-data/"
            "fhvhv_tripdata_2026-05.parquet",
        )
        self.assertIn("2026-05: downloading https://", output)
        self.assertTrue(rideshare_file_path("2026-05", self.data_dir).exists())
        self.assertEqual(number_after("Rows kept", block(output, "2026-05")), 1)

    # Command errors.

    def test_repeated_month_is_an_error(self):
        with self.assertRaisesMessage(
            CommandError, "Each month can be given only once: 2026-03"
        ):
            self.run_import("2026-03", "2026-04", "2026-03")

        self.assertFalse(RideshareRouteHourStats.objects.exists())

    def test_month_is_required(self):
        with self.assertRaisesMessage(CommandError, "--month"):
            self.run_import()

    def test_badly_formed_month_is_an_error(self):
        for bad in ("2026-3", "2026-13", "March"):
            with self.subTest(bad=bad):
                with self.assertRaisesMessage(CommandError, bad):
                    self.run_import(bad)

        self.assertFalse(RideshareRouteHourStats.objects.exists())
