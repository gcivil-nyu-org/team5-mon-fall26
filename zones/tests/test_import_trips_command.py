import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.error import URLError

from django.core.management import CommandError, call_command
from django.db.models import Sum
from django.test import TestCase

from zones.importer.download import trip_file_path
from zones.models import RouteHourStats, Zone, ZoneHourStats
from zones.tests.importer_helpers import make_trips, write_parquet

# 3 March trips, 2 kept (one has zero distance).
MARCH = make_trips({}, {"pickup_zone_id": 4}, {"trip_distance": 0.0})
# 3 trips in the April file, 2 kept (one picks up in March).
APRIL = make_trips(
    {"pickup_at": "2026-04-07 18:00:00", "dropoff_at": "2026-04-07 18:30:00"},
    {"pickup_at": "2026-04-07 18:05:00", "dropoff_at": "2026-04-07 18:25:00"},
    {"pickup_at": "2026-03-31 23:00:00", "dropoff_at": "2026-03-31 23:20:00"},
)


def trip_total(model):
    return model.objects.aggregate(total=Sum("trip_count"))["total"]


def stats_rows(model):
    fields = [f.attname for f in model._meta.concrete_fields if f.name != "id"]
    return list(model.objects.order_by(*fields).values_list(*fields))


class ImportTripsCommandTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        write_parquet(MARCH, trip_file_path("2026-03", self.data_dir))
        write_parquet(APRIL, trip_file_path("2026-04", self.data_dir))

        # The tests never touch the network.
        patcher = mock.patch(
            "zones.importer.download.urlopen", side_effect=URLError("no network in tests")
        )
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)

    def run_import(self, *months):
        out = StringIO()
        args = []
        for month in months:
            args += ["--month", month]
        call_command("import_trips", *args, "--data-dir", str(self.data_dir), stdout=out)
        return out.getvalue()

    def test_imports_months_end_to_end(self):
        output = self.run_import("2026-03", "2026-04")

        self.assertEqual(Zone.objects.count(), 265)
        self.assertEqual(trip_total(ZoneHourStats), 4)
        self.assertEqual(trip_total(RouteHourStats), 4)
        # The two April trips share a zone and an hour.
        self.assertEqual(ZoneHourStats.objects.get(zone_id=161, day_of_week=1, hour=18).trip_count, 2)
        self.assertFalse(ZoneHourStats.objects.filter(zone_id__in=[264, 265]).exists())
        self.urlopen.assert_not_called()

        self.assertIn("Months loaded: 2026-03, 2026-04", output)
        self.assertIn("Total (2 months)", output)
        self.assertRegex(output, r"Rows kept\s+4\n")
        self.assertRegex(output, r"Rows removed\s+2\s+\(33\.33%\)")

    def test_running_twice_gives_the_same_rows(self):
        self.run_import("2026-03", "2026-04")
        first = (stats_rows(ZoneHourStats), stats_rows(RouteHourStats), Zone.objects.count())

        self.run_import("2026-03", "2026-04")

        self.assertEqual(
            (stats_rows(ZoneHourStats), stats_rows(RouteHourStats), Zone.objects.count()),
            first,
        )

    def test_fewer_months_replace_all_stats(self):
        self.run_import("2026-03", "2026-04")

        output = self.run_import("2026-03")

        self.assertEqual(trip_total(ZoneHourStats), 2)
        self.assertEqual(trip_total(RouteHourStats), 2)
        self.assertIn("Months loaded: 2026-03\n", output)

    def test_repeated_month_is_an_error(self):
        with self.assertRaisesMessage(CommandError, "2026-03"):
            self.run_import("2026-03", "2026-04", "2026-03")

        self.assertFalse(ZoneHourStats.objects.exists())

    def test_month_is_required(self):
        with self.assertRaisesMessage(CommandError, "--month"):
            self.run_import()

    def test_badly_formed_month_is_an_error(self):
        with self.assertRaisesMessage(CommandError, "2026-3"):
            self.run_import("2026-3")

    def test_bad_file_is_an_error_and_keeps_the_old_stats(self):
        self.run_import("2026-03", "2026-04")
        before = stats_rows(RouteHourStats)
        write_parquet(MARCH.drop(columns=["fare_amount"]), trip_file_path("2026-05", self.data_dir))

        with self.assertRaisesMessage(CommandError, "fare_amount"):
            self.run_import("2026-03", "2026-05")

        self.assertEqual(stats_rows(RouteHourStats), before)

    def test_failed_download_is_an_error_and_keeps_the_old_stats(self):
        self.run_import("2026-03")
        before = stats_rows(RouteHourStats)

        with self.assertRaisesMessage(CommandError, "2026-06"):
            self.run_import("2026-03", "2026-06")

        self.assertEqual(stats_rows(RouteHourStats), before)
        self.assertFalse(trip_file_path("2026-06", self.data_dir).exists())
