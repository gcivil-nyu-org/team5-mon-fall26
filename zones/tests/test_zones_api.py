import gzip
import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from zones.models import Zone, ZoneHourStats


def add_stats(zone, day, hour, trip_count):
    return ZoneHourStats.objects.create(
        zone=zone,
        day_of_week=day,
        hour=hour,
        trip_count=trip_count,
        avg_duration_min=10.0,
        fare_min=Decimal("5.00"),
        fare_avg=Decimal("15.00"),
        fare_max=Decimal("40.00"),
    )


class ZonesApiTests(TestCase):
    def setUp(self):
        self.jfk = Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")
        self.midtown = Zone.objects.create(zone_id=161, name="Midtown Center", borough="Manhattan")
        add_stats(self.jfk, day=0, hour=9, trip_count=500)
        add_stats(self.midtown, day=0, hour=9, trip_count=1200)
        add_stats(self.jfk, day=1, hour=9, trip_count=7)  # other day, must not leak in

    def get(self, **params):
        return self.client.get(reverse("zones:zones_api"), params)

    def by_id(self, response):
        return {f["properties"]["zone_id"]: f for f in response.json()["features"]}

    def test_returns_all_263_zones_with_boundaries(self):
        response = self.get(day=0, hour=9)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 263)
        for feature in data["features"]:
            self.assertIn(feature["geometry"]["type"], ("Polygon", "MultiPolygon"))

    def test_trip_count_is_for_the_requested_day_and_hour(self):
        zones = self.by_id(self.get(day=0, hour=9))

        self.assertEqual(zones[132]["properties"]["trip_count"], 500)
        self.assertEqual(zones[161]["properties"]["trip_count"], 1200)

    def test_zone_without_stats_gets_zero(self):
        zones = self.by_id(self.get(day=0, hour=9))

        self.assertEqual(zones[1]["properties"]["trip_count"], 0)

    def test_each_zone_has_name_and_borough(self):
        zones = self.by_id(self.get(day=0, hour=9))

        self.assertEqual(zones[132]["properties"]["name"], "JFK Airport")
        self.assertEqual(zones[132]["properties"]["borough"], "Queens")
        for feature in zones.values():
            self.assertTrue(feature["properties"]["name"])
            self.assertTrue(feature["properties"]["borough"])

    def test_echoes_day_and_hour(self):
        data = self.get(day=0, hour=9).json()

        self.assertEqual((data["day"], data["hour"]), (0, 9))

    def test_defaults_to_a_valid_day_and_hour(self):
        data = self.get().json()

        self.assertIn(data["day"], range(7))
        self.assertIn(data["hour"], range(24))

    def test_bad_day_or_hour_returns_400(self):
        for params in ({"day": 7, "hour": 9}, {"day": 0, "hour": 24},
                       {"day": "mon", "hour": 9}, {"day": -1, "hour": 0}):
            with self.subTest(params=params):
                self.assertEqual(self.get(**params).status_code, 400)

    def test_post_not_allowed(self):
        response = self.client.post(reverse("zones:zones_api"))

        self.assertEqual(response.status_code, 405)


class ZonesApiGZipTests(TestCase):
    """The ~2.5 MB /api/zones response is served gzip-compressed when the
    client accepts it (GZipMiddleware), and as plain JSON otherwise."""

    def test_gzip_accept_encoding_returns_compressed_response(self):
        response = self.client.get(reverse("zones:zones_api"), HTTP_ACCEPT_ENCODING="gzip")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Encoding"), "gzip")
        data = json.loads(gzip.decompress(response.content))
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 263)

    def test_without_gzip_accept_encoding_returns_plain_json(self):
        response = self.client.get(reverse("zones:zones_api"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Encoding", response.headers)
        data = response.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 263)
