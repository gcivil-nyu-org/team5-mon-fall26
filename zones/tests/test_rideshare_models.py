from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from zones.models import RideshareRouteHourStats, RideshareZoneHourStats, Zone

STATS = {
    "day_of_week": 1,
    "hour": 17,
    "trip_count": 10,
    "avg_duration_min": 20.0,
    "fare_min": Decimal("8.00"),
    "fare_avg": Decimal("15.00"),
    "fare_max": Decimal("30.00"),
    "avg_wait_min": 4.5,
    "wait_count": 9,
    "fare_per_mile": Decimal("6.25"),
}


class RideshareModelTests(TestCase):
    def setUp(self):
        self.pickup = Zone.objects.create(zone_id=3, name="Astoria", borough="Queens")
        self.dropoff = Zone.objects.create(
            zone_id=4, name="Midtown", borough="Manhattan"
        )

    def route(self, **overrides):
        return RideshareRouteHourStats.objects.create(
            pickup_zone=self.pickup, dropoff_zone=self.dropoff, **{**STATS, **overrides}
        )

    def zone(self, **overrides):
        return RideshareZoneHourStats.objects.create(
            zone=self.pickup, **{**STATS, **overrides}
        )

    def test_route_row_saves_and_reads_back(self):
        fetched = RideshareRouteHourStats.objects.get(pk=self.route().pk)

        self.assertEqual(fetched.pickup_zone, self.pickup)
        self.assertEqual(fetched.dropoff_zone, self.dropoff)
        self.assertEqual(fetched.fare_per_mile, Decimal("6.25"))
        self.assertEqual(fetched.avg_wait_min, 4.5)
        self.assertEqual(fetched.wait_count, 9)
        self.assertEqual(list(self.pickup.rideshare_routes_from.all()), [fetched])
        self.assertEqual(list(self.dropoff.rideshare_routes_to.all()), [fetched])

    def test_zone_row_saves_and_reads_back(self):
        fetched = RideshareZoneHourStats.objects.get(pk=self.zone().pk)

        self.assertEqual(fetched.zone, self.pickup)
        self.assertEqual(fetched.trip_count, 10)
        self.assertEqual(list(self.pickup.rideshare_hour_stats.all()), [fetched])

    def test_wait_and_fare_per_mile_can_be_null(self):
        route = self.route(avg_wait_min=None, wait_count=0, fare_per_mile=None)
        zone = self.zone(avg_wait_min=None, wait_count=0, fare_per_mile=None)

        for model, pk in (
            (RideshareRouteHourStats, route.pk),
            (RideshareZoneHourStats, zone.pk),
        ):
            fetched = model.objects.get(pk=pk)
            self.assertIsNone(fetched.avg_wait_min)
            self.assertIsNone(fetched.fare_per_mile)

    def test_route_cell_is_unique(self):
        self.route()
        self.route(hour=18)  # a different cell is fine

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.route(trip_count=99)

    def test_zone_cell_is_unique(self):
        self.zone()
        self.zone(day_of_week=2)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.zone(trip_count=99)

    def test_deleting_a_zone_cascades(self):
        self.route()
        self.zone()

        self.pickup.delete()

        self.assertEqual(RideshareRouteHourStats.objects.count(), 0)
        self.assertEqual(RideshareZoneHourStats.objects.count(), 0)

    def test_str(self):
        self.assertEqual(str(self.route()), "pickup=3 dropoff=4 day=1 hour=17")
        self.assertEqual(str(self.zone()), "zone=3 day=1 hour=17")
