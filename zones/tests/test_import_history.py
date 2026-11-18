"""US40 #114: every taxi and rideshare import, successful or failed, saves
one ImportRun with the numbers of the report it prints."""

import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.error import URLError

from django.core.management import CommandError, call_command
from django.db import DatabaseError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from zones.importer import history
from zones.importer import load as taxi_load
from zones.importer.clean import RULES as TAXI_RULES
from zones.importer.download import trip_file_path
from zones.importer.rideshare import load as rideshare_load
from zones.importer.rideshare.clean import RULES as RIDESHARE_RULES
from zones.importer.rideshare.download import rideshare_file_path
from zones.models import (
    ImportRun,
    RideshareRouteHourStats,
    RouteHourStats,
    ZoneHourStats,
)
from zones.tests import test_import_rideshare_command as rideshare_cmd
from zones.tests import test_import_trips_command as taxi_cmd
from zones.tests.importer_helpers import write_parquet
from zones.tests.rideshare_helpers import write_trips
from zones.tests.test_import_rideshare_command import block, number_after

TAXI_LABELS = dict(TAXI_RULES)
RIDESHARE_LABELS = dict(RIDESHARE_RULES)


class ImportFiles:
    """Small taxi and rideshare files for March and April 2026, the same
    ones the command tests use, and no network."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        write_parquet(taxi_cmd.MARCH, trip_file_path("2026-03", self.data_dir))
        write_parquet(taxi_cmd.APRIL, trip_file_path("2026-04", self.data_dir))
        write_trips(rideshare_file_path("2026-03", self.data_dir), *rideshare_cmd.MARCH)
        write_trips(rideshare_file_path("2026-04", self.data_dir), *rideshare_cmd.APRIL)

        patcher = mock.patch(
            "zones.importer.download.urlopen",
            side_effect=URLError("no network in tests"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        user = mock.patch.object(history.getpass, "getuser", return_value="os-user")
        user.start()
        self.addCleanup(user.stop)

    def run_command(self, command, *months, by=None, stderr=None):
        out = StringIO()
        args = []
        for month in months:
            args += ["--month", month]
        if by is not None:
            args += ["--by", by]
        call_command(
            command,
            *args,
            "--data-dir",
            str(self.data_dir),
            stdout=out,
            stderr=stderr or StringIO(),
        )
        return out.getvalue()

    def taxi(self, *months, **kwargs):
        return self.run_command("import_trips", *months, **kwargs)

    def rideshare(self, *months, **kwargs):
        return self.run_command("import_rideshare", *months, **kwargs)


def assert_matches_block(test, run, report, labels):
    """The record's totals are the numbers in the report's Total block."""
    total = block(report, "Total")
    test.assertEqual(run.rows_read, number_after("Rows read", total))
    test.assertEqual(run.rows_removed, number_after("Rows removed", total))
    test.assertEqual(run.rows_kept, number_after("Rows kept", total))
    test.assertEqual(set(run.removed_by_rule), set(labels))
    for key, label in labels.items():
        test.assertEqual(run.removed_by_rule[key], number_after(label, total), key)
    cells = block(report, "Zone cells")
    test.assertEqual(run.zone_cells, number_after("Zone cells", cells))
    test.assertEqual(run.route_cells, number_after("Route cells", cells))
    zone_line, route_line = cells.splitlines()
    test.assertIn(f"({run.small_zone_cells} with fewer than", zone_line)
    test.assertIn(f"({run.small_route_cells} with fewer than", route_line)
    test.assertIn(f"fewer than {run.min_trip_count} trips", zone_line)


class TaxiImportHistoryTests(ImportFiles, TestCase):
    # AC1 and AC2: one record per import, with the report's numbers.

    def test_successful_import_saves_one_record_with_the_report_numbers(self):
        before = timezone.now()

        output = self.taxi("2026-03", "2026-04")

        run = ImportRun.objects.get()
        self.assertEqual(run.dataset, ImportRun.Dataset.TAXI)
        self.assertEqual(run.status, ImportRun.Status.SUCCEEDED)
        self.assertEqual(run.months, ["2026-03", "2026-04"])
        self.assertEqual(run.run_by, "os-user")
        self.assertEqual(run.error, "")
        self.assertLessEqual(before, run.started_at)
        self.assertLessEqual(run.started_at, run.finished_at)
        self.assertLessEqual(run.finished_at, timezone.now())

        self.assertEqual((run.rows_read, run.rows_removed, run.rows_kept), (6, 2, 4))
        self.assertEqual(run.removed_by_rule["bad_distance"], 1)
        self.assertEqual(run.removed_by_rule["pickup_outside_month"], 1)
        self.assertIsNone(run.waits_left_out)
        self.assertEqual((run.zone_cells, run.route_cells), (3, 3))
        self.assertEqual(run.zone_cells, ZoneHourStats.objects.count())
        self.assertEqual(run.route_cells, RouteHourStats.objects.count())
        self.assertEqual((run.small_zone_cells, run.small_route_cells), (3, 3))
        self.assertEqual(run.min_trip_count, 5)
        self.assertEqual(run.zones_loaded, 265)
        assert_matches_block(self, run, output, TAXI_LABELS)

    def test_record_keeps_the_report_exactly_as_printed(self):
        output = self.taxi("2026-03", "2026-04")

        report = ImportRun.objects.get().report
        self.assertTrue(report.startswith("Months loaded: 2026-03, 2026-04\n"))
        self.assertIn(f"\n{report}\n", output)

    def test_record_keeps_the_cleaning_limits(self):
        self.taxi("2026-03")

        self.assertEqual(
            ImportRun.objects.get().cleaning_limits,
            {
                "MAX_FARE_CENTS": 50_000,
                "MAX_DISTANCE_MI": 100,
                "MIN_DURATION_S": 60,
                "MAX_DURATION_S": 10_800,
                "UNKNOWN_ZONE_IDS": [264, 265],
                "VOIDED_PAYMENT_TYPE": 6,
            },
        )

    def test_each_run_adds_one_record(self):
        self.taxi("2026-03", "2026-04")
        self.taxi("2026-03")

        runs = list(ImportRun.objects.all())
        self.assertEqual(len(runs), 2)
        # Newest first.
        self.assertEqual(runs[0].months, ["2026-03"])
        self.assertEqual(runs[0].rows_read, 3)
        self.assertEqual(runs[1].rows_read, 6)

    # Who ran it.

    def test_by_names_who_ran_the_import(self):
        self.taxi("2026-03", by="  data team ")

        self.assertEqual(ImportRun.objects.get().run_by, "data team")

    def test_blank_by_is_an_error_and_saves_nothing(self):
        with self.assertRaisesMessage(CommandError, "--by"):
            self.taxi("2026-03", by="  ")

        self.assertFalse(ImportRun.objects.exists())

    def test_too_long_by_is_an_error(self):
        with self.assertRaisesMessage(CommandError, "--by"):
            self.taxi("2026-03", by="x" * 151)

    def test_unknown_operating_system_user(self):
        with mock.patch.object(history.getpass, "getuser", side_effect=OSError):
            self.taxi("2026-03")

        self.assertEqual(ImportRun.objects.get().run_by, "unknown")

    # AC1 and AC3: a failed import saves one record with its error.

    def test_bad_file_saves_a_failed_record_and_keeps_the_old_stats(self):
        self.taxi("2026-03", "2026-04")
        before = taxi_cmd.stats_rows(RouteHourStats)
        write_parquet(
            taxi_cmd.MARCH.drop(columns=["fare_amount"]),
            trip_file_path("2026-05", self.data_dir),
        )

        with self.assertRaisesMessage(CommandError, "fare_amount") as raised:
            self.taxi("2026-03", "2026-05")

        self.assertEqual(taxi_cmd.stats_rows(RouteHourStats), before)
        run = ImportRun.objects.first()
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertEqual(run.months, ["2026-03", "2026-05"])
        self.assertEqual(run.error, str(raised.exception))
        self.assertIsNotNone(run.finished_at)
        self.assertIsNone(run.rows_read)
        self.assertIsNone(run.zone_cells)
        self.assertEqual(run.report, "")
        self.assertEqual(ImportRun.objects.count(), 2)

    def test_failed_download_saves_a_failed_record(self):
        with self.assertRaises(CommandError):
            self.taxi("2026-06")

        run = ImportRun.objects.get()
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertIn("Could not download 2026-06", run.error)

    def test_failure_while_writing_saves_the_error_and_keeps_the_old_stats(self):
        self.taxi("2026-03")
        before = taxi_cmd.stats_rows(ZoneHourStats)
        real_bulk_insert = taxi_load._bulk_insert

        def fail_on_routes(model, build, stats, batch_size):
            if model is RouteHourStats:
                raise RuntimeError("disk full")
            return real_bulk_insert(model, build, stats, batch_size)

        with mock.patch.object(taxi_load, "_bulk_insert", fail_on_routes):
            with self.assertRaisesMessage(RuntimeError, "disk full"):
                self.taxi("2026-03", "2026-04")

        self.assertEqual(taxi_cmd.stats_rows(ZoneHourStats), before)
        run = ImportRun.objects.first()
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertEqual(run.error, "RuntimeError: disk full")

    def test_error_without_a_message_records_its_type(self):
        with mock.patch("zones.importer.pipeline.load_all", side_effect=MemoryError):
            with self.assertRaises(MemoryError):
                self.taxi("2026-03")

        self.assertEqual(ImportRun.objects.get().error, "MemoryError")

    def test_interrupted_import_saves_a_failed_record(self):
        with mock.patch(
            "zones.importer.pipeline.clean_trips", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.taxi("2026-03")

        run = ImportRun.objects.get()
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertEqual(run.error, history.INTERRUPTED)

    def test_failure_to_save_the_failed_run_keeps_the_original_error(self):
        stderr = StringIO()

        with mock.patch.object(
            history, "record_failure", side_effect=DatabaseError("db gone")
        ):
            with self.assertRaisesMessage(CommandError, "2026-06"):
                self.taxi("2026-06", stderr=stderr)

        self.assertIn("Could not save the failed run", stderr.getvalue())
        self.assertIn("db gone", stderr.getvalue())

    # Rejected before the import starts: not an import, so no record.

    def test_argument_errors_save_no_record(self):
        for months in (("2026-03", "2026-03"), ("2026-3",), ()):
            with self.subTest(months=months):
                with self.assertRaises(CommandError):
                    self.taxi(*months)

        self.assertFalse(ImportRun.objects.exists())

    # A run that never finished (killed, out of memory).

    def test_next_run_closes_an_unfinished_run_of_the_same_import(self):
        started = timezone.now() - timedelta(hours=2)
        stuck = ImportRun.objects.create(
            dataset=ImportRun.Dataset.TAXI,
            months=["2026-03"],
            run_by="someone",
            started_at=started,
            min_trip_count=5,
            cleaning_limits={},
        )
        other = ImportRun.objects.create(
            dataset=ImportRun.Dataset.RIDESHARE,
            months=["2026-03"],
            run_by="someone",
            started_at=started,
            min_trip_count=5,
            cleaning_limits={},
        )

        self.taxi("2026-03")

        stuck.refresh_from_db()
        other.refresh_from_db()
        new = ImportRun.objects.first()
        self.assertEqual(stuck.status, ImportRun.Status.FAILED)
        self.assertIn("Did not finish", stuck.error)
        self.assertIn(f"run {new.pk}", stuck.error)
        self.assertIsNone(stuck.finished_at)
        self.assertEqual(other.status, ImportRun.Status.RUNNING)
        self.assertEqual(new.status, ImportRun.Status.SUCCEEDED)


class RideshareImportHistoryTests(ImportFiles, TestCase):
    def test_successful_import_saves_one_record_with_the_report_numbers(self):
        output = self.rideshare("2026-03", "2026-04", by="po")

        run = ImportRun.objects.get()
        self.assertEqual(run.dataset, ImportRun.Dataset.RIDESHARE)
        self.assertEqual(run.status, ImportRun.Status.SUCCEEDED)
        self.assertEqual(run.months, ["2026-03", "2026-04"])
        self.assertEqual(run.run_by, "po")
        self.assertEqual((run.rows_read, run.rows_removed, run.rows_kept), (8, 3, 5))
        self.assertEqual(run.removed_by_rule["shared_ride"], 1)
        self.assertEqual(run.removed_by_rule["unknown_zone"], 1)
        self.assertEqual(run.removed_by_rule["pickup_outside_month"], 1)
        self.assertEqual(run.waits_left_out, 1)
        self.assertEqual(
            run.waits_left_out,
            number_after("Waits left out of the average", block(output, "Total")),
        )
        self.assertEqual(run.route_cells, RideshareRouteHourStats.objects.count())
        self.assertEqual(run.zones_loaded, 265)
        assert_matches_block(self, run, output, RIDESHARE_LABELS)
        self.assertIn(f"\n{run.report}\n", output)

    def test_record_keeps_the_rideshare_cleaning_limits(self):
        self.rideshare("2026-03")

        limits = ImportRun.objects.get().cleaning_limits
        self.assertEqual(limits["MAX_FARE_CENTS"], 50_000)
        self.assertEqual(limits["PROVIDERS"], ["HV0003", "HV0005"])
        self.assertEqual((limits["MIN_WAIT_S"], limits["MAX_WAIT_S"]), (0, 3600))
        self.assertNotIn("VOIDED_PAYMENT_TYPE", limits)

    def test_failure_while_writing_saves_a_failed_record(self):
        self.rideshare("2026-03")
        before = rideshare_cmd.rideshare_rows()
        real_copy_rows = rideshare_load.copy_rows

        def fail_on_routes(model, columns, rows):
            if model is RideshareRouteHourStats:
                raise RuntimeError("connection lost")
            return real_copy_rows(model, columns, rows)

        with mock.patch.object(rideshare_load, "copy_rows", fail_on_routes):
            with self.assertRaises(RuntimeError):
                self.rideshare("2026-03", "2026-04")

        self.assertEqual(rideshare_cmd.rideshare_rows(), before)
        run = ImportRun.objects.first()
        self.assertEqual(run.dataset, ImportRun.Dataset.RIDESHARE)
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertEqual(run.error, "RuntimeError: connection lost")

    def test_bad_file_saves_a_failed_record(self):
        write_trips(rideshare_file_path("2026-05", self.data_dir), {}, drop=["tolls"])

        with self.assertRaisesMessage(CommandError, "tolls"):
            self.rideshare("2026-05")

        run = ImportRun.objects.get()
        self.assertEqual(run.status, ImportRun.Status.FAILED)
        self.assertIn("tolls", run.error)

    def test_argument_errors_save_no_record(self):
        with self.assertRaises(CommandError):
            self.rideshare("2026-03", "2026-03")

        self.assertFalse(ImportRun.objects.exists())

    def test_taxi_and_rideshare_runs_are_kept_apart(self):
        self.taxi("2026-03")
        self.rideshare("2026-03")

        self.assertEqual(
            list(ImportRun.objects.values_list("dataset", flat=True)),
            [ImportRun.Dataset.RIDESHARE, ImportRun.Dataset.TAXI],
        )


class FailedRunIsCommittedTests(ImportFiles, TransactionTestCase):
    """Committed for real (no test transaction around it): the import's
    own transaction rolls back, but the failed record stays."""

    def test_taxi_failure_after_the_delete_keeps_old_stats_and_the_record(self):
        self.taxi("2026-03")
        before = taxi_cmd.stats_rows(RouteHourStats), taxi_cmd.stats_rows(ZoneHourStats)
        real_bulk_insert = taxi_load._bulk_insert

        def fail_on_routes(model, build, stats, batch_size):
            if model is RouteHourStats:
                # Inside the import's transaction the old rows are gone.
                self.assertFalse(RouteHourStats.objects.exists())
                raise RuntimeError("disk full")
            return real_bulk_insert(model, build, stats, batch_size)

        with mock.patch.object(taxi_load, "_bulk_insert", fail_on_routes):
            with self.assertRaises(RuntimeError):
                self.taxi("2026-03", "2026-04")

        after = taxi_cmd.stats_rows(RouteHourStats), taxi_cmd.stats_rows(ZoneHourStats)
        self.assertEqual(after, before)
        statuses = list(ImportRun.objects.values_list("status", "error"))
        self.assertEqual(
            statuses,
            [
                (ImportRun.Status.FAILED, "RuntimeError: disk full"),
                (ImportRun.Status.SUCCEEDED, ""),
            ],
        )

    def test_rideshare_failure_after_the_truncate_keeps_old_rows_and_the_record(
        self,
    ):
        self.rideshare("2026-03")
        before = rideshare_cmd.rideshare_rows()
        real_copy_rows = rideshare_load.copy_rows

        def fail_on_routes(model, columns, rows):
            if model is RideshareRouteHourStats:
                raise RuntimeError("connection lost")
            return real_copy_rows(model, columns, rows)

        with mock.patch.object(rideshare_load, "copy_rows", fail_on_routes):
            with self.assertRaises(RuntimeError):
                self.rideshare("2026-03", "2026-04")

        self.assertEqual(rideshare_cmd.rideshare_rows(), before)
        self.assertEqual(ImportRun.objects.first().status, ImportRun.Status.FAILED)
        self.assertEqual(ImportRun.objects.count(), 2)


class ImportRunModelTests(TestCase):
    def make(self, **fields):
        values = {
            "dataset": ImportRun.Dataset.TAXI,
            "months": ["2026-03", "2026-04"],
            "run_by": "po",
            "started_at": timezone.now(),
            "min_trip_count": 5,
            "cleaning_limits": {},
            **fields,
        }
        return ImportRun.objects.create(**values)

    def test_str_names_the_import_months_and_status(self):
        run = self.make()

        self.assertEqual(str(run), f"Yellow taxi 2026-03, 2026-04 (Running) #{run.pk}")

    def test_months_text(self):
        self.assertEqual(self.make().months_text, "2026-03, 2026-04")

    def test_duration(self):
        started = timezone.now()
        run = self.make(started_at=started, finished_at=started + timedelta(seconds=95))

        self.assertEqual(run.duration, timedelta(seconds=95))
        self.assertIsNone(self.make().duration)

    def test_newest_first(self):
        now = timezone.now()
        old = self.make(started_at=now - timedelta(days=1))
        new = self.make(started_at=now)

        self.assertEqual(list(ImportRun.objects.all()), [new, old])
