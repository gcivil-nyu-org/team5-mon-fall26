from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from zones.importer import aggregate as taxi_aggregate
from zones.importer.load import load_all
from zones.importer.read import read_zone_lookup
from zones.importer.rideshare import load as rideshare_load
from zones.importer.rideshare.aggregate import Totals
from zones.importer.rideshare.load import load_rideshare
from zones.models import (
    RideshareRouteHourStats,
    RideshareZoneHourStats,
    RouteHourStats,
    Zone,
    ZoneHourStats,
)
from zones.tests import importer_helpers
from zones.tests.rideshare_helpers import make_kept
from zones.tests.test_rideshare_aggregate import HAND_CHECKED

# Fares whose exact value ends in a half cent, so rounding half up
# (not to even) shows: 3757 / 2 = 1878.5 cents, 1005 / 1000 = 1.005 $/mi.
HALF_CENTS = make_kept(
    (1, 2, 0, 0, 600, 1878, 500, None),
    (1, 2, 0, 0, 600, 1879, 500, None),
    (1, 2, 0, 1, 600, 1005, 1000, None),
)

OTHER = make_kept((1, 2, 0, 0, 600, 1000, 300, 60))


def stats_for(kept):
    totals = Totals()
    totals.add(kept)
    return totals.stats()


def table_rows(model):
    fields = [f.attname for f in model._meta.concrete_fields if f.name != "id"]
    return list(model.objects.order_by(*fields).values_list(*fields))


def rideshare_rows():
    return table_rows(RideshareZoneHourStats), table_rows(RideshareRouteHourStats)


class LoadRideshareTests(TestCase):
    def setUp(self):
        self.lookup = read_zone_lookup()

    def test_fills_zones_and_both_tables(self):
        counts = load_rideshare(self.lookup, *stats_for(HAND_CHECKED))

        self.assertEqual(counts, (265, 2, 4))
        self.assertEqual(Zone.objects.count(), 265)
        self.assertEqual(RideshareZoneHourStats.objects.count(), 2)
        self.assertEqual(RideshareRouteHourStats.objects.count(), 4)

    def test_route_cell_reads_back_hand_checked(self):
        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))

        route = RideshareRouteHourStats.objects.get(
            pickup_zone_id=161, dropoff_zone_id=237, day_of_week=1, hour=8
        )
        self.assertEqual(route.pickup_zone.name, "Midtown Center")
        self.assertEqual(route.dropoff_zone.name, "Upper East Side South")
        self.assertEqual(route.trip_count, 3)
        self.assertEqual(route.avg_duration_min, 12.0)
        self.assertEqual(route.fare_min, Decimal("18.65"))
        self.assertEqual(route.fare_avg, Decimal("19.19"))  # 57.56 / 3 = 19.1867
        self.assertEqual(route.fare_max, Decimal("20.01"))
        self.assertEqual(route.avg_wait_min, 3.5)  # (5 + 2) / 2, one left out
        self.assertEqual(route.wait_count, 2)
        self.assertEqual(route.fare_per_mile, Decimal("7.59"))  # 57.56 / 7.58

    def test_zone_cell_reads_back_hand_checked(self):
        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))

        zone = RideshareZoneHourStats.objects.get(zone_id=161, day_of_week=1, hour=8)
        self.assertEqual(zone.trip_count, 4)
        self.assertEqual(zone.avg_duration_min, 2460 / 4 / 60)
        self.assertEqual(zone.fare_min, Decimal("15.00"))
        self.assertEqual(zone.fare_avg, Decimal("18.14"))  # 72.56 / 4
        self.assertEqual(zone.fare_max, Decimal("20.01"))
        self.assertEqual(zone.avg_wait_min, 480 / 3 / 60)
        self.assertEqual(zone.wait_count, 3)
        self.assertEqual(zone.fare_per_mile, Decimal("8.46"))  # 72.56 / 8.58

    def test_all_waits_left_out_stores_null_wait(self):
        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))

        route = RideshareRouteHourStats.objects.get(
            pickup_zone_id=4, dropoff_zone_id=237
        )
        self.assertIsNone(route.avg_wait_min)
        self.assertEqual(route.wait_count, 0)
        self.assertEqual(route.trip_count, 2)
        self.assertEqual(route.fare_per_mile, Decimal("3.57"))  # 50.00 / 14.00

    def test_miles_rounded_to_zero_store_null_fare_per_mile(self):
        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))

        route = RideshareRouteHourStats.objects.get(
            pickup_zone_id=4, dropoff_zone_id=161
        )
        self.assertIsNone(route.fare_per_mile)
        self.assertEqual(route.avg_wait_min, 10.0)

    def test_fares_round_half_up_to_the_cent(self):
        load_rideshare(self.lookup, *stats_for(HALF_CENTS))

        hour0 = RideshareRouteHourStats.objects.get(hour=0)
        hour1 = RideshareRouteHourStats.objects.get(hour=1)
        self.assertEqual(hour0.fare_avg, Decimal("18.79"))  # 18.785
        self.assertEqual(hour0.fare_per_mile, Decimal("3.76"))  # 37.57 / 10 = 3.757
        self.assertEqual(hour1.fare_per_mile, Decimal("1.01"))  # 10.05 / 10 = 1.005

    def test_second_run_replaces_instead_of_adding(self):
        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))
        first = rideshare_rows()

        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))

        self.assertEqual(rideshare_rows(), first)
        self.assertEqual(RideshareZoneHourStats.objects.count(), 2)
        self.assertEqual(RideshareRouteHourStats.objects.count(), 4)

    def test_new_data_removes_old_cells(self):
        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))

        load_rideshare(self.lookup, *stats_for(OTHER))

        self.assertEqual(
            list(RideshareZoneHourStats.objects.values_list("zone_id", flat=True)),
            [1],
        )
        self.assertEqual(RideshareRouteHourStats.objects.count(), 1)

    def test_failure_partway_keeps_the_old_data(self):
        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))
        before = rideshare_rows()
        changed = self.lookup.copy()
        changed.loc[changed["zone_id"] == 1, "name"] = "Changed"

        # The zone table is already copied and one route row sent when the
        # second route row fails.
        real_route_row = rideshare_load._route_row
        calls = []

        def fail_on_second(row):
            calls.append(row)
            if len(calls) == 2:
                raise RuntimeError("connection lost")
            return real_route_row(row)

        with (
            mock.patch.object(rideshare_load, "_route_row", fail_on_second),
            mock.patch.object(rideshare_load, "analyze_stats") as analyze,
        ):
            with self.assertRaises(RuntimeError):
                load_rideshare(changed, *stats_for(HALF_CENTS))

        self.assertEqual(len(calls), 2)
        analyze.assert_not_called()
        self.assertEqual(rideshare_rows(), before)
        self.assertEqual(Zone.objects.get(zone_id=1).name, "Newark Airport")

    def test_taxi_tables_are_never_touched(self):
        taxi_kept = importer_helpers.make_kept(
            (161, 237, 1, 8, 600, 1890), (4, 161, 6, 23, 300, 750)
        )
        load_all(
            self.lookup,
            taxi_aggregate.finalize(
                taxi_aggregate.partial_totals(taxi_kept, taxi_aggregate.ZONE_KEYS)
            ),
            taxi_aggregate.finalize(
                taxi_aggregate.partial_totals(taxi_kept, taxi_aggregate.ROUTE_KEYS)
            ),
        )
        taxi_before = table_rows(ZoneHourStats), table_rows(RouteHourStats)
        taxi_ids = list(RouteHourStats.objects.values_list("id", flat=True))

        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))
        load_rideshare(self.lookup, *stats_for(OTHER))

        self.assertEqual(
            (table_rows(ZoneHourStats), table_rows(RouteHourStats)), taxi_before
        )
        self.assertEqual(
            list(RouteHourStats.objects.values_list("id", flat=True)), taxi_ids
        )

    def test_analyzes_both_rideshare_tables_after_loading(self):
        with mock.patch.object(rideshare_load, "analyze_stats") as analyze:
            load_rideshare(self.lookup, *stats_for(HAND_CHECKED))

        analyze.assert_called_once_with(
            (RideshareZoneHourStats, RideshareRouteHourStats)
        )

    def test_analyze_runs_on_postgres(self):
        # Not mocked: ANALYZE must be valid SQL for both tables.
        load_rideshare(self.lookup, *stats_for(OTHER))

        self.assertEqual(RideshareRouteHourStats.objects.count(), 1)


def statements(queries, verb):
    return [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith(verb)]


class TruncateReplaceTests(TestCase):
    """The rideshare replace empties the tables with TRUNCATE (docs/decisions.md,
    US27d); the taxi replace keeps DELETE."""

    def setUp(self):
        self.lookup = read_zone_lookup()

    def test_replace_truncates_both_rideshare_tables_only(self):
        load_rideshare(self.lookup, *stats_for(HAND_CHECKED))

        with CaptureQueriesContext(connection) as queries:
            load_rideshare(self.lookup, *stats_for(OTHER))

        truncates = statements(queries.captured_queries, "TRUNCATE")
        self.assertEqual(len(truncates), 1)
        for model in (RideshareZoneHourStats, RideshareRouteHourStats):
            self.assertIn(model._meta.db_table, truncates[0])
        for model in (ZoneHourStats, RouteHourStats, Zone):
            self.assertNotIn(f'"{model._meta.db_table}"', truncates[0])
        self.assertEqual(statements(queries.captured_queries, "DELETE"), [])

    def test_taxi_replace_still_deletes(self):
        empty = taxi_aggregate.finalize(
            taxi_aggregate.partial_totals(
                importer_helpers.make_kept((161, 237, 1, 8, 600, 1890)),
                taxi_aggregate.ZONE_KEYS,
            )
        )
        with CaptureQueriesContext(connection) as queries:
            load_all(self.lookup, empty, empty.iloc[0:0])

        self.assertEqual(statements(queries.captured_queries, "TRUNCATE"), [])
        self.assertEqual(len(statements(queries.captured_queries, "DELETE")), 2)


class TruncateRollbackTests(TransactionTestCase):
    """Committed for real (no test transaction around it), so this shows that
    PostgreSQL rolls back the TRUNCATE itself when the load fails."""

    def test_failed_replace_after_truncate_keeps_the_committed_rows(self):
        lookup = read_zone_lookup()
        load_rideshare(lookup, *stats_for(HAND_CHECKED))
        before = rideshare_rows()
        real_copy_rows = rideshare_load.copy_rows

        def fail_on_routes(model, columns, rows):
            if model is RideshareRouteHourStats:
                # Inside the transaction the old routes are gone by now.
                self.assertFalse(RideshareRouteHourStats.objects.exists())
                raise RuntimeError("connection lost")
            return real_copy_rows(model, columns, rows)

        with mock.patch.object(rideshare_load, "copy_rows", fail_on_routes):
            with self.assertRaises(RuntimeError):
                load_rideshare(lookup, *stats_for(OTHER))

        self.assertEqual(rideshare_rows(), before)
