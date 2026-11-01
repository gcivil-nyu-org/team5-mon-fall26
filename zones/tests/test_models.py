from decimal import Decimal

from django.test import TestCase

from zones.models import RouteHourStats, Zone, ZoneHourStats


class ZoneModelTests(TestCase):
    def test_zone_saves_and_reads_back(self):
        zone = Zone.objects.create(
            zone_id=1,
            name="Newark Airport",
            borough="EWR",
        )

        fetched = Zone.objects.get(zone_id=1)

        self.assertEqual(fetched.name, "Newark Airport")
        self.assertEqual(fetched.borough, "EWR")
        self.assertEqual(fetched, zone)

    def test_zone_str(self):
        zone = Zone.objects.create(zone_id=1, name="Newark Airport", borough="EWR")

        self.assertEqual(str(zone), "1 Newark Airport (EWR)")


class ZoneHourStatsModelTests(TestCase):
    def test_stats_row_saves_and_reads_back(self):
        zone = Zone.objects.create(zone_id=2, name="Jamaica Bay", borough="Queens")

        stats = ZoneHourStats.objects.create(
            zone=zone,
            day_of_week=0,  # Monday
            hour=9,
            trip_count=42,
            avg_duration_min=12.5,
            fare_min=Decimal("5.00"),
            fare_avg=Decimal("14.25"),
            fare_max=Decimal("38.00"),
        )

        fetched = ZoneHourStats.objects.get(pk=stats.pk)

        self.assertEqual(fetched.zone, zone)
        self.assertEqual(fetched.trip_count, 42)
        self.assertEqual(fetched.fare_avg, Decimal("14.25"))

    def test_zone_hour_stats_str(self):
        zone = Zone.objects.create(zone_id=2, name="Jamaica Bay", borough="Queens")
        stats = ZoneHourStats.objects.create(
            zone=zone,
            day_of_week=0,
            hour=9,
            trip_count=42,
            avg_duration_min=12.5,
            fare_min=Decimal("5.00"),
            fare_avg=Decimal("14.25"),
            fare_max=Decimal("38.00"),
        )

        self.assertEqual(str(stats), "zone=2 day=0 hour=9")


class RouteHourStatsModelTests(TestCase):
    def test_route_stats_row_saves_and_reads_back(self):
        pickup = Zone.objects.create(zone_id=3, name="Astoria", borough="Queens")
        dropoff = Zone.objects.create(zone_id=4, name="Midtown", borough="Manhattan")

        stats = RouteHourStats.objects.create(
            pickup_zone=pickup,
            dropoff_zone=dropoff,
            day_of_week=1,
            hour=17,
            trip_count=10,
            avg_duration_min=20.0,
            fare_min=Decimal("8.00"),
            fare_avg=Decimal("15.00"),
            fare_max=Decimal("30.00"),
        )

        fetched = RouteHourStats.objects.get(pk=stats.pk)

        self.assertEqual(fetched.pickup_zone, pickup)
        self.assertEqual(fetched.dropoff_zone, dropoff)
        self.assertEqual(fetched.trip_count, 10)

    def test_route_hour_stats_str(self):
        pickup = Zone.objects.create(zone_id=3, name="Astoria", borough="Queens")
        dropoff = Zone.objects.create(zone_id=4, name="Midtown", borough="Manhattan")
        stats = RouteHourStats.objects.create(
            pickup_zone=pickup,
            dropoff_zone=dropoff,
            day_of_week=1,
            hour=17,
            trip_count=10,
            avg_duration_min=20.0,
            fare_min=Decimal("8.00"),
            fare_avg=Decimal("15.00"),
            fare_max=Decimal("30.00"),
        )

        self.assertEqual(str(stats), "pickup=3 dropoff=4 day=1 hour=17")
