"""US28 #75: GET /api/routes/rideshare, the Uber and Lyft twin of
/api/routes (same validation and enough_data rule, rideshare tables)."""

from datetime import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from zones.models import RideshareRouteHourStats, RideshareZoneHourStats, Zone
from zones.stats import rideshare_route_stats

RESPONSE_KEYS = {
    "from",
    "to",
    "day",
    "hour",
    "enough_data",
    "trip_count",
    "fare_min",
    "fare_avg",
    "fare_max",
    "avg_duration_min",
    "avg_wait_min",
}
STAT_KEYS = ("fare_min", "fare_avg", "fare_max", "avg_duration_min", "avg_wait_min")


def rideshare_values(trip_count, wait_count, fare_avg, avg_wait_min):
    return {
        "trip_count": trip_count,
        "avg_duration_min": 12.5,
        "fare_min": Decimal("9.10"),
        "fare_avg": Decimal(fare_avg),
        "fare_max": Decimal("61.20"),
        "avg_wait_min": avg_wait_min,
        "wait_count": wait_count,
        "fare_per_mile": Decimal("7.25"),
    }


def add_rideshare_route(
    pickup,
    dropoff,
    day,
    hour,
    trip_count,
    wait_count=None,
    fare_avg="24.40",
    avg_wait_min=4.5,
):
    return RideshareRouteHourStats.objects.create(
        pickup_zone=pickup,
        dropoff_zone=dropoff,
        day_of_week=day,
        hour=hour,
        **rideshare_values(
            trip_count,
            trip_count if wait_count is None else wait_count,
            fare_avg,
            avg_wait_min,
        ),
    )


def add_rideshare_zone(zone, day, hour, trip_count, fare_avg="27.00"):
    return RideshareZoneHourStats.objects.create(
        zone=zone,
        day_of_week=day,
        hour=hour,
        **rideshare_values(trip_count, trip_count, fare_avg, 3.75),
    )


class RideshareData:
    """The zone row and the route row for the same cell have different
    average fares, so each test shows which table was read."""

    @classmethod
    def setUpTestData(cls):
        cls.midtown = Zone.objects.create(
            zone_id=161, name="Midtown Center", borough="Manhattan"
        )
        cls.ues = Zone.objects.create(
            zone_id=237, name="Upper East Side South", borough="Manhattan"
        )
        cls.jfk = Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")

        # Monday (0) 8:00 unless noted.
        add_rideshare_zone(cls.midtown, 0, 8, 1200, fare_avg="27.00")
        add_rideshare_route(cls.midtown, cls.ues, 0, 8, 85, fare_avg="24.40")
        # Exactly the minimum: enough data.
        add_rideshare_route(cls.midtown, cls.ues, 0, 9, 5, fare_avg="25.00")
        # One under the minimum: not enough data.
        add_rideshare_route(cls.midtown, cls.ues, 0, 3, 4)
        # Enough trips, but only 4 valid waits: the wait is hidden.
        add_rideshare_route(cls.midtown, cls.jfk, 0, 8, 40, wait_count=4)
        # Enough trips, no valid wait at all (avg_wait_min stored as null).
        add_rideshare_route(
            cls.midtown, cls.jfk, 0, 9, 40, wait_count=0, avg_wait_min=None
        )
        # A trip within one zone.
        add_rideshare_route(cls.midtown, cls.midtown, 0, 8, 30, fare_avg="11.10")
        # Only the zone table has Tuesday (1) 8:00 for Midtown Center.
        add_rideshare_zone(cls.midtown, 1, 8, 50)


class RideshareRouteStatsTests(RideshareData, TestCase):
    def test_route_reads_the_route_table(self):
        stats = rideshare_route_stats(161, 237, 0, 8)
        self.assertEqual(
            stats,
            {
                "enough_data": True,
                "trip_count": 85,
                "fare_min": Decimal("9.10"),
                "fare_avg": Decimal("24.40"),
                "fare_max": Decimal("61.20"),
                "avg_duration_min": 12.5,
                "avg_wait_min": 4.5,
            },
        )

    def test_pickup_only_reads_the_zone_table(self):
        stats = rideshare_route_stats(161, None, 0, 8)
        self.assertTrue(stats["enough_data"])
        self.assertEqual(stats["trip_count"], 1200)
        self.assertEqual(stats["fare_avg"], Decimal("27.00"))
        self.assertEqual(stats["avg_wait_min"], 3.75)

    def test_a_sparse_route_never_falls_back_to_the_zone(self):
        # Tuesday 8:00 exists in the zone table only.
        stats = rideshare_route_stats(161, 237, 1, 8)
        self.assertFalse(stats["enough_data"])
        self.assertEqual(stats["trip_count"], 0)

    def test_minimum_trip_count_is_enough(self):
        stats = rideshare_route_stats(161, 237, 0, 9)
        self.assertTrue(stats["enough_data"])
        self.assertEqual(stats["trip_count"], 5)

    def test_below_minimum_gives_null_stats_and_the_real_count(self):
        stats = rideshare_route_stats(161, 237, 0, 3)
        self.assertFalse(stats["enough_data"])
        self.assertEqual(stats["trip_count"], 4)
        for key in STAT_KEYS:
            self.assertIsNone(stats[key], key)

    def test_no_row_gives_zero_trips(self):
        stats = rideshare_route_stats(237, 161, 6, 23)
        self.assertEqual(
            stats, {"enough_data": False, "trip_count": 0, **dict.fromkeys(STAT_KEYS)}
        )

    def test_too_few_waits_hides_only_the_wait(self):
        stats = rideshare_route_stats(161, 132, 0, 8)
        self.assertTrue(stats["enough_data"])
        self.assertIsNone(stats["avg_wait_min"])
        self.assertEqual(stats["fare_avg"], Decimal("24.40"))
        self.assertNotIn("wait_count", stats)

    def test_no_valid_wait_gives_a_null_wait(self):
        stats = rideshare_route_stats(161, 132, 0, 9)
        self.assertTrue(stats["enough_data"])
        self.assertIsNone(stats["avg_wait_min"])

    @override_settings(MIN_TRIP_COUNT=100)
    def test_uses_the_shared_setting(self):
        self.assertFalse(rideshare_route_stats(161, 237, 0, 8)["enough_data"])
        self.assertTrue(rideshare_route_stats(161, None, 0, 8)["enough_data"])


class RideshareRoutesApiTests(RideshareData, TestCase):
    url = reverse("zones:rideshare_routes_api")

    def get(self, **params):
        return self.client.get(self.url, params)

    def test_url(self):
        self.assertEqual(self.url, "/api/routes/rideshare")

    def test_route_response(self):
        response = self.get(**{"from": 161, "to": 237, "day": 0, "hour": 8})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), RESPONSE_KEYS)
        self.assertEqual(
            data,
            {
                "from": 161,
                "to": 237,
                "day": 0,
                "hour": 8,
                "enough_data": True,
                "trip_count": 85,
                "fare_min": "9.10",
                "fare_avg": "24.40",
                "fare_max": "61.20",
                "avg_duration_min": 12.5,
                "avg_wait_min": 4.5,
            },
        )

    def test_pickup_only(self):
        for params in ({"from": 161}, {"from": 161, "to": ""}):
            with self.subTest(params=params):
                data = self.get(**params, day=0, hour=8).json()
                self.assertIsNone(data["to"])
                self.assertEqual(data["fare_avg"], "27.00")

    def test_trip_within_one_zone(self):
        data = self.get(**{"from": 161, "to": 161, "day": 0, "hour": 8}).json()
        self.assertTrue(data["enough_data"])
        self.assertEqual(data["fare_avg"], "11.10")

    def test_not_enough_data_is_200_with_null_stats(self):
        response = self.get(**{"from": 161, "to": 237, "day": 0, "hour": 3})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["enough_data"])
        self.assertEqual(data["trip_count"], 4)
        for key in STAT_KEYS:
            self.assertIsNone(data[key], key)

    def test_defaults_to_the_current_nyc_day_and_hour(self):
        # Monday 2026-11-09 08:30 in New York.
        monday_8am = datetime(2026, 11, 9, 8, 30)
        with mock.patch("zones.views.datetime") as fake:
            fake.now.return_value = monday_8am
            data = self.get(**{"from": 161, "to": 237}).json()
        self.assertEqual((data["day"], data["hour"]), (0, 8))
        self.assertEqual(data["trip_count"], 85)

    def test_bad_parameters_give_400(self):
        bad = [
            {},
            {"from": ""},
            {"from": "abc"},
            {"from": 0},
            {"from": 999},
            {"from": 50},  # a valid id that is not in the zone table
            {"from": 161, "to": "x"},
            {"from": 161, "to": 50},
            {"from": 161, "day": 7},
            {"from": 161, "day": -1},
            {"from": 161, "hour": 24},
            {"from": 161, "hour": "noon"},
        ]
        for params in bad:
            with self.subTest(params=params):
                response = self.get(**params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_same_error_as_api_routes(self):
        params = {"from": 161, "day": 9}
        rideshare = self.get(**params).json()
        taxi = self.client.get(reverse("zones:routes_api"), params).json()
        self.assertEqual(rideshare, taxi)

    def test_only_get(self):
        response = self.client.post(self.url, {"from": 161})
        self.assertEqual(response.status_code, 405)

    def test_no_account_needed(self):
        response = self.get(**{"from": 161, "to": 237, "day": 0, "hour": 8})
        self.assertEqual(response.status_code, 200)


class RidesharePanelTemplateTests(TestCase):
    """The trip summary has the "Taxi vs. rideshare" section (US28 #75)."""

    def setUp(self):
        self.response = self.client.get(reverse("zones:map"))
        self.html = self.response.content.decode()

    def test_section_is_inside_the_trip_summary_and_starts_hidden(self):
        self.assertContains(self.response, "Taxi vs. rideshare")
        summary = self.html.index('id="summary-panel"')
        section = self.html.index('id="rideshare-panel"')
        self.assertLess(summary, section)
        self.assertIn('id="rideshare-panel" class="rideshare-panel" hidden', self.html)

    def test_both_sides_have_fare_range_and_duration_cells(self):
        for cell in (
            "rideshare-taxi-fare",
            "rideshare-taxi-range",
            "rideshare-taxi-duration",
            "rideshare-ride-fare",
            "rideshare-ride-range",
            "rideshare-ride-duration",
            "rideshare-ride-wait",
        ):
            with self.subTest(cell=cell):
                self.assertContains(self.response, f'id="{cell}"')

    def test_labeled_as_historical_not_live_prices(self):
        self.assertContains(self.response, "Historical, not live prices")
        self.assertContains(self.response, "higher during a surge")

    def test_script_loaded_after_filters_js(self):
        self.assertIn("zones/js/rideshare.js", self.html)
        self.assertLess(
            self.html.index("zones/js/filters.js"),
            self.html.index("zones/js/rideshare.js"),
        )
