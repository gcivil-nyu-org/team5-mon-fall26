from decimal import Decimal

from django.test import TestCase

from zones.models import Zone, ZoneHourStats


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
