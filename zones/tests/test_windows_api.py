"""US7 #9: Find Best and Worst Travel Times — route_windows() and
GET /api/routes/windows."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from zones.models import Zone
from zones.stats import route_windows

from .test_routes_api import add_route_stats, add_zone_stats


class WindowData:
    """Monday (0) unless noted. Midtown -> UES is the main route: its
    cheapest and fastest hour is 3:00 (exactly 5 trips), and 9:00 would
    beat it but has only 4 trips. 17:00 and 18:00 tie on fare; 18:00 is
    the slowest."""

    @classmethod
    def setUpTestData(cls):
        cls.midtown = Zone.objects.create(zone_id=161, name="Midtown Center", borough="Manhattan")
        cls.ues = Zone.objects.create(zone_id=237, name="Upper East Side South", borough="Manhattan")
        cls.jfk = Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")

        add_route_stats(cls.midtown, cls.ues, 0, 3, 5, fare_avg="12.00", avg_duration_min=9.0)
        add_route_stats(cls.midtown, cls.ues, 0, 7, 50, fare_avg="20.00", avg_duration_min=15.0)
        add_route_stats(cls.midtown, cls.ues, 0, 8, 412, fare_avg="17.43", avg_duration_min=11.62)
        add_route_stats(cls.midtown, cls.ues, 0, 9, 4, fare_avg="5.00", avg_duration_min=2.0)
        add_route_stats(cls.midtown, cls.ues, 0, 17, 300, fare_avg="25.50", avg_duration_min=30.0)
        add_route_stats(cls.midtown, cls.ues, 0, 18, 200, fare_avg="25.50", avg_duration_min=35.0)
        # Other day: must not leak into Monday.
        add_route_stats(cls.midtown, cls.ues, 1, 4, 99, fare_avg="1.00", avg_duration_min=1.0)

        # Pickup only: all trips from Midtown.
        add_zone_stats(cls.midtown, 0, 8, 900, fare_avg="21.07", avg_duration_min=14.25)
        add_zone_stats(cls.midtown, 0, 10, 100, fare_avg="30.00", avg_duration_min=20.0)

        # Only one hour with enough trips.
        add_route_stats(cls.jfk, cls.ues, 0, 8, 7, fare_avg="70.00", avg_duration_min=40.0)
        add_route_stats(cls.jfk, cls.ues, 0, 9, 4, fare_avg="65.00", avg_duration_min=38.0)


class RouteWindowsTests(WindowData, TestCase):
    """route_windows() ranks the day's hours by fare and by duration."""

    def test_ranks_hours_by_fare_and_by_duration(self):
        result = route_windows(161, 237, 0)

        self.assertIs(result["enough_data"], True)
        self.assertEqual(result["by_fare"], [3, 8, 7, 17, 18])
        self.assertEqual(result["by_duration"], [3, 8, 7, 17, 18])

    def test_best_is_cheapest_and_fastest_hour(self):
        result = route_windows(161, 237, 0)

        self.assertEqual(result["best"]["fare"]["hour"], 3)
        self.assertEqual(result["best"]["fare"]["fare_avg"], Decimal("12.00"))
        self.assertEqual(result["best"]["duration"]["hour"], 3)
        self.assertEqual(result["best"]["duration"]["avg_duration_min"], 9.0)

    def test_worst_is_most_expensive_and_slowest_hour(self):
        result = route_windows(161, 237, 0)

        # 17:00 and 18:00 tie at $25.50: the earlier hour wins.
        self.assertEqual(result["worst"]["fare"]["hour"], 17)
        self.assertEqual(result["worst"]["duration"]["hour"], 18)
        self.assertEqual(result["worst"]["duration"]["avg_duration_min"], 35.0)

    def test_hours_below_minimum_are_left_out(self):
        result = route_windows(161, 237, 0)

        self.assertNotIn(9, [h["hour"] for h in result["hours"]])
        self.assertNotIn(9, result["by_fare"])

    def test_hours_list_matches_rows_in_hour_order(self):
        hours = route_windows(161, 237, 0)["hours"]

        self.assertEqual([h["hour"] for h in hours], [3, 7, 8, 17, 18])
        self.assertEqual(
            hours[2],
            {"hour": 8, "trip_count": 412, "fare_avg": Decimal("17.43"), "avg_duration_min": 11.62},
        )

    def test_other_day_does_not_leak(self):
        self.assertEqual(route_windows(161, 237, 1)["enough_data"], False)
        self.assertNotIn(4, route_windows(161, 237, 0)["by_fare"])

    def test_pickup_only_reads_zone_stats(self):
        result = route_windows(161, None, 0)

        self.assertEqual(result["by_fare"], [8, 10])
        self.assertEqual(result["best"]["fare"]["hour"], 8)
        self.assertEqual(result["worst"]["fare"]["hour"], 10)
        self.assertEqual(result["worst"]["duration"]["hour"], 10)

    def test_one_qualifying_hour_is_not_enough_data(self):
        self.assert_not_enough(route_windows(132, 237, 0))

    def test_route_without_rows_is_not_enough_data(self):
        self.assert_not_enough(route_windows(237, 161, 0))

    @override_settings(MIN_TRIP_COUNT=6)
    def test_minimum_comes_from_the_setting(self):
        result = route_windows(161, 237, 0)

        self.assertNotIn(3, result["by_fare"])
        self.assertEqual(result["best"]["fare"]["hour"], 8)

    def assert_not_enough(self, result):
        self.assertEqual(
            result,
            {"enough_data": False, "hours": [], "by_fare": [], "by_duration": [],
             "best": None, "worst": None},
        )


class RouteWindowsApiTests(WindowData, TestCase):
    """GET /api/routes/windows over HTTP."""

    def get(self, **params):
        return self.client.get(reverse("zones:route_windows_api"), params)

    def test_pickup_only_returns_full_contract(self):
        response = self.get(**{"from": 161, "day": 0})

        self.assertEqual(response.status_code, 200)
        eight = {"hour": 8, "trip_count": 900, "fare_avg": "21.07", "avg_duration_min": 14.25}
        ten = {"hour": 10, "trip_count": 100, "fare_avg": "30.00", "avg_duration_min": 20.0}
        self.assertEqual(
            response.json(),
            {
                "from": 161,
                "to": None,
                "day": 0,
                "enough_data": True,
                "hours": [eight, ten],
                "by_fare": [8, 10],
                "by_duration": [8, 10],
                "best": {"fare": eight, "duration": eight},
                "worst": {"fare": ten, "duration": ten},
            },
        )

    def test_route_values_match_the_rows(self):
        data = self.get(**{"from": 161, "to": 237, "day": 0}).json()

        self.assertEqual(data["to"], 237)
        self.assertEqual(data["best"]["fare"]["fare_avg"], "12.00")
        self.assertEqual(data["worst"]["fare"]["fare_avg"], "25.50")
        self.assertEqual(data["worst"]["duration"]["avg_duration_min"], 35.0)

    def test_empty_to_means_pickup_only(self):
        data = self.get(**{"from": 161, "to": "", "day": 0}).json()

        self.assertIsNone(data["to"])
        self.assertEqual(data["by_fare"], [8, 10])

    def test_not_enough_data_is_200_and_empty(self):
        response = self.get(**{"from": 132, "to": 237, "day": 0})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIs(data["enough_data"], False)
        self.assertEqual(data["hours"], [])
        self.assertIsNone(data["best"])
        self.assertIsNone(data["worst"])

    def test_defaults_to_a_valid_day(self):
        response = self.get(**{"from": 161})

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()["day"], range(7))

    def test_missing_or_invalid_parameters_return_400(self):
        cases = [
            {},
            {"from": "abc", "day": 0},
            {"from": 999, "day": 0},
            {"from": 161, "to": "abc", "day": 0},
            {"from": 161, "to": 999, "day": 0},
            {"from": 161, "day": 7},
            {"from": 161, "day": -1},
        ]
        for params in cases:
            with self.subTest(params=params):
                self.assertEqual(self.get(**params).status_code, 400)

    def test_post_not_allowed(self):
        response = self.client.post(reverse("zones:route_windows_api"))

        self.assertEqual(response.status_code, 405)
