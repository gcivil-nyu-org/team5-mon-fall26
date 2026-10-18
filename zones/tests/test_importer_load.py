from decimal import Decimal
from unittest import mock

from django.test import TestCase

from zones.importer.aggregate import ROUTE_KEYS, ZONE_KEYS, finalize, partial_totals
from zones.importer.load import load_all, replace_stats, upsert_zones
from zones.importer.read import read_zone_lookup
from zones.models import RouteHourStats, Zone, ZoneHourStats
from zones.tests.importer_helpers import make_kept

KEPT = make_kept(
    (161, 237, 1, 8, 600, 1890),
    (161, 237, 1, 8, 660, 1865),
    (161, 230, 1, 8, 900, 2000),
    (4, 237, 6, 23, 1200, 3000),
    (4, 161, 6, 23, 300, 750),
)


def stats_for(kept):
    return (
        finalize(partial_totals(kept, ZONE_KEYS)),
        finalize(partial_totals(kept, ROUTE_KEYS)),
    )


def stats_rows(model):
    fields = [f.attname for f in model._meta.concrete_fields if f.name != "id"]
    return list(model.objects.order_by(*fields).values_list(*fields))


class UpsertZonesTests(TestCase):
    def test_creates_every_zone(self):
        count = upsert_zones(read_zone_lookup())

        self.assertEqual(count, 265)
        self.assertEqual(Zone.objects.count(), 265)
        self.assertEqual(Zone.objects.get(zone_id=265).name, "Outside of NYC")

    def test_second_run_updates_in_place(self):
        lookup = read_zone_lookup()
        upsert_zones(lookup)

        changed = lookup.copy()
        changed.loc[changed["zone_id"] == 1, "name"] = "Newark Liberty Airport"
        upsert_zones(changed)

        self.assertEqual(Zone.objects.count(), 265)
        self.assertEqual(Zone.objects.get(zone_id=1).name, "Newark Liberty Airport")

    def test_does_not_delete_existing_stats(self):
        lookup = read_zone_lookup()
        upsert_zones(lookup)
        replace_stats(*stats_for(KEPT))

        upsert_zones(lookup)

        self.assertEqual(ZoneHourStats.objects.count(), 2)
        self.assertEqual(RouteHourStats.objects.count(), 4)


class ReplaceStatsTests(TestCase):
    def setUp(self):
        upsert_zones(read_zone_lookup())

    def test_rows_read_back_with_decimal_fares_and_zones(self):
        counts = replace_stats(*stats_for(KEPT))

        self.assertEqual(counts, (2, 4))
        zone_cell = ZoneHourStats.objects.get(zone_id=161, day_of_week=1, hour=8)
        self.assertEqual(zone_cell.trip_count, 3)
        self.assertEqual(zone_cell.avg_duration_min, (600 + 660 + 900) / 3 / 60)
        self.assertEqual(zone_cell.fare_min, Decimal("18.65"))
        self.assertEqual(zone_cell.fare_avg, Decimal("19.18"))  # 57.55 / 3 = 19.1833
        self.assertEqual(zone_cell.fare_max, Decimal("20.00"))

        route = RouteHourStats.objects.get(
            pickup_zone_id=161, dropoff_zone_id=237, day_of_week=1, hour=8
        )
        self.assertEqual(route.pickup_zone.name, "Midtown Center")
        self.assertEqual(route.dropoff_zone.name, "Upper East Side South")
        self.assertEqual(route.trip_count, 2)
        self.assertEqual(route.fare_avg, Decimal("18.78"))  # 18.775 rounded half up
        self.assertEqual(route.avg_duration_min, 10.5)

    def test_second_run_replaces_instead_of_adding(self):
        replace_stats(*stats_for(KEPT))
        first = (stats_rows(ZoneHourStats), stats_rows(RouteHourStats))

        replace_stats(*stats_for(KEPT))

        self.assertEqual((stats_rows(ZoneHourStats), stats_rows(RouteHourStats)), first)
        self.assertEqual(ZoneHourStats.objects.count(), 2)
        self.assertEqual(RouteHourStats.objects.count(), 4)

    def test_new_data_removes_old_cells(self):
        replace_stats(*stats_for(KEPT))

        replace_stats(*stats_for(make_kept((1, 2, 0, 0, 600, 1000))))

        self.assertEqual(list(ZoneHourStats.objects.values_list("zone_id", flat=True)), [1])
        self.assertEqual(RouteHourStats.objects.count(), 1)

    def test_rows_are_written_in_batches(self):
        zone_stats, route_stats = stats_for(KEPT)

        with mock.patch.object(
            RouteHourStats.objects, "bulk_create", wraps=RouteHourStats.objects.bulk_create
        ) as bulk_create:
            replace_stats(zone_stats, route_stats, batch_size=2)

        self.assertEqual(RouteHourStats.objects.count(), 4)
        self.assertEqual([len(call.args[0]) for call in bulk_create.call_args_list], [2, 2])


class LoadAllTests(TestCase):
    def test_fills_all_three_tables(self):
        counts = load_all(read_zone_lookup(), *stats_for(KEPT))

        self.assertEqual(counts, (265, 2, 4))
        self.assertEqual(Zone.objects.count(), 265)
        self.assertEqual(ZoneHourStats.objects.count(), 2)
        self.assertEqual(RouteHourStats.objects.count(), 4)

    def test_failure_halfway_keeps_the_old_data(self):
        lookup = read_zone_lookup()
        load_all(lookup, *stats_for(KEPT))
        before = (stats_rows(ZoneHourStats), stats_rows(RouteHourStats))

        changed = lookup.copy()
        changed.loc[changed["zone_id"] == 1, "name"] = "Changed"
        with mock.patch.object(
            RouteHourStats.objects, "bulk_create", side_effect=RuntimeError("disk full")
        ):
            with self.assertRaises(RuntimeError):
                load_all(changed, *stats_for(make_kept((1, 2, 0, 0, 600, 1000))))

        self.assertEqual((stats_rows(ZoneHourStats), stats_rows(RouteHourStats)), before)
        self.assertEqual(Zone.objects.get(zone_id=1).name, "Newark Airport")
