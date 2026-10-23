from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from zones.models import RouteHourStats, Zone, ZoneHourStats
from zones.stats import route_stats

STAT_KEYS = ("fare_min", "fare_avg", "fare_max", "avg_duration_min")


def add_zone_stats(zone, day, hour, trip_count, fare_min="5.00", fare_avg="15.00",
                   fare_max="40.00", avg_duration_min=10.0):
    return ZoneHourStats.objects.create(
        zone=zone,
        day_of_week=day,
        hour=hour,
        trip_count=trip_count,
        avg_duration_min=avg_duration_min,
        fare_min=Decimal(fare_min),
        fare_avg=Decimal(fare_avg),
        fare_max=Decimal(fare_max),
    )


def add_route_stats(pickup, dropoff, day, hour, trip_count, fare_min="5.00",
                    fare_avg="15.00", fare_max="40.00", avg_duration_min=10.0):
    return RouteHourStats.objects.create(
        pickup_zone=pickup,
        dropoff_zone=dropoff,
        day_of_week=day,
        hour=hour,
        trip_count=trip_count,
        avg_duration_min=avg_duration_min,
        fare_min=Decimal(fare_min),
        fare_avg=Decimal(fare_avg),
        fare_max=Decimal(fare_max),
    )


class RouteData:
    """Shared rows. The zone row and the route rows for the same cell have
    different values, so each test shows which table was read."""

    @classmethod
    def setUpTestData(cls):
        cls.midtown = Zone.objects.create(zone_id=161, name="Midtown Center", borough="Manhattan")
        cls.ues = Zone.objects.create(zone_id=237, name="Upper East Side South", borough="Manhattan")
        cls.jfk = Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")
        cls.battery = Zone.objects.create(zone_id=12, name="Battery Park", borough="Manhattan")
        cls.rockaway = Zone.objects.create(zone_id=201, name="Rockaway Park", borough="Queens")

        # Monday (0) 8:00 unless noted.
        cls.midtown_zone = add_zone_stats(
            cls.midtown, 0, 8, 900, "3.50", "21.07", "95.10", 14.25)
        cls.midtown_ues = add_route_stats(
            cls.midtown, cls.ues, 0, 8, 412, "9.80", "17.43", "48.25", 11.62)
        cls.midtown_midtown = add_route_stats(
            cls.midtown, cls.midtown, 0, 8, 37, "4.20", "11.89", "26.75", 6.5)
        # Must not leak into Midtown -> UES Monday 8:00.
        add_route_stats(cls.midtown, cls.jfk, 0, 8, 60, "70.00", "88.00", "120.00", 45.0)
        add_route_stats(cls.midtown, cls.ues, 0, 9, 300, "1.00", "2.00", "3.00", 1.0)
        add_route_stats(cls.midtown, cls.ues, 1, 8, 300, "1.00", "2.00", "3.00", 1.0)

        # Minimum trip count boundary: 5 is shown, 4 is not.
        cls.five_route = add_route_stats(cls.battery, cls.rockaway, 0, 8, 5, "30.00", "41.67", "55.00", 40.0)
        cls.four_route = add_route_stats(cls.rockaway, cls.battery, 0, 8, 4)
        cls.five_zone = add_zone_stats(cls.battery, 0, 8, 5, "8.00", "12.34", "19.99", 9.0)
        cls.four_zone = add_zone_stats(cls.rockaway, 0, 8, 4)

        # Busy pickup zone with no row for this route.
        add_zone_stats(cls.jfk, 0, 8, 3000)

        cls.seven_route = add_route_stats(cls.jfk, cls.ues, 2, 18, 7)


class RouteStatsTests(RouteData, TestCase):
    """route_stats() without HTTP."""

    def assert_row(self, result, row):
        self.assertEqual(result["enough_data"], True)
        self.assertEqual(result["trip_count"], row.trip_count)
        self.assertEqual(result["fare_min"], row.fare_min)
        self.assertEqual(result["fare_avg"], row.fare_avg)
        self.assertEqual(result["fare_max"], row.fare_max)
        self.assertEqual(result["avg_duration_min"], row.avg_duration_min)

    def assert_not_enough(self, result, trip_count):
        self.assertEqual(result["enough_data"], False)
        self.assertEqual(result["trip_count"], trip_count)
        for key in STAT_KEYS:
            self.assertIsNone(result[key], key)

    def test_both_zones_returns_route_row(self):
        self.assert_row(route_stats(161, 237, 0, 8), self.midtown_ues)

    def test_pickup_only_returns_zone_row(self):
        self.assert_row(route_stats(161, None, 0, 8), self.midtown_zone)

    def test_from_equals_to_returns_that_route_row(self):
        self.assert_row(route_stats(161, 161, 0, 8), self.midtown_midtown)

    def test_values_match_rows_exactly(self):
        result = route_stats(161, 237, 0, 8)

        self.assertIsInstance(result["fare_avg"], Decimal)
        self.assertEqual(result["fare_min"], Decimal("9.80"))
        self.assertEqual(result["fare_avg"], Decimal("17.43"))  # as stored
        self.assertEqual(result["fare_max"], Decimal("48.25"))
        self.assertEqual(result["avg_duration_min"], 11.62)

    def test_exactly_five_trips_is_shown(self):
        self.assert_row(route_stats(12, 201, 0, 8), self.five_route)
        self.assert_row(route_stats(12, None, 0, 8), self.five_zone)

    def test_four_trips_is_not_enough_data(self):
        self.assert_not_enough(route_stats(201, 12, 0, 8), trip_count=4)
        self.assert_not_enough(route_stats(201, None, 0, 8), trip_count=4)

    def test_missing_cell_is_not_enough_data_with_zero_trips(self):
        self.assert_not_enough(route_stats(237, 161, 0, 8), trip_count=0)
        self.assert_not_enough(route_stats(237, None, 0, 8), trip_count=0)

    def test_route_without_row_does_not_fall_back_to_zone_stats(self):
        self.assert_not_enough(route_stats(132, 237, 0, 8), trip_count=0)

    def test_other_day_hour_and_dropoff_do_not_leak(self):
        self.assert_row(route_stats(161, 237, 0, 8), self.midtown_ues)
        self.assert_not_enough(route_stats(161, 237, 0, 10), trip_count=0)
        self.assert_not_enough(route_stats(161, 237, 2, 8), trip_count=0)

    @override_settings(MIN_TRIP_COUNT=10)
    def test_minimum_comes_from_the_setting(self):
        self.assert_not_enough(route_stats(132, 237, 2, 18), trip_count=7)

    def test_default_minimum_is_five(self):
        self.assert_row(route_stats(132, 237, 2, 18), self.seven_route)


class RoutesApiTests(RouteData, TestCase):
    """GET /api/routes over HTTP."""

    def get(self, **params):
        return self.client.get(reverse("zones:routes_api"), params)

    def test_both_zones_returns_full_contract(self):
        response = self.get(**{"from": 161, "to": 237, "day": 0, "hour": 8})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "from": 161,
                "to": 237,
                "day": 0,
                "hour": 8,
                "enough_data": True,
                "trip_count": 412,
                "fare_min": "9.80",
                "fare_avg": "17.43",
                "fare_max": "48.25",
                "avg_duration_min": 11.62,
            },
        )

    def test_fares_match_the_row(self):
        data = self.get(**{"from": 161, "to": 237, "day": 0, "hour": 8}).json()

        for key in ("fare_min", "fare_avg", "fare_max"):
            self.assertEqual(Decimal(data[key]), getattr(self.midtown_ues, key), key)

    def test_pickup_only_reads_zone_stats(self):
        data = self.get(**{"from": 161, "day": 0, "hour": 8}).json()

        self.assertIsNone(data["to"])
        self.assertEqual(data["trip_count"], 900)
        self.assertEqual(data["fare_avg"], "21.07")

    def test_empty_to_means_pickup_only(self):
        data = self.get(**{"from": 161, "to": "", "day": 0, "hour": 8}).json()

        self.assertIsNone(data["to"])
        self.assertEqual(data["trip_count"], 900)

    def test_from_equals_to(self):
        response = self.get(**{"from": 161, "to": 161, "day": 0, "hour": 8})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["from"], data["to"]), (161, 161))
        self.assertEqual(data["trip_count"], 37)
        self.assertEqual(data["fare_avg"], "11.89")

    def test_not_enough_data_is_200_with_null_stats(self):
        response = self.get(**{"from": 201, "to": 12, "day": 0, "hour": 8})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIs(data["enough_data"], False)
        self.assertEqual(data["trip_count"], 4)
        for key in STAT_KEYS:
            self.assertIsNone(data[key], key)

    def test_exactly_five_trips_is_shown(self):
        data = self.get(**{"from": 12, "to": 201, "day": 0, "hour": 8}).json()

        self.assertIs(data["enough_data"], True)
        self.assertEqual(data["fare_avg"], "41.67")

    def test_missing_cell_has_zero_trips(self):
        data = self.get(**{"from": 237, "to": 161, "day": 0, "hour": 8}).json()

        self.assertIs(data["enough_data"], False)
        self.assertEqual(data["trip_count"], 0)

    def test_known_zone_without_statistics_is_not_enough_data(self):
        Zone.objects.create(zone_id=264, name="Unknown", borough="Unknown")
        Zone.objects.create(zone_id=265, name="Outside of NYC", borough="N/A")
        cases = (
            {"from": 264, "day": 0, "hour": 8},
            {"from": 161, "to": 265, "day": 0, "hour": 8},
        )
        for params in cases:
            with self.subTest(params=params):
                response = self.get(**params)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertIs(data["enough_data"], False)
                self.assertEqual(data["trip_count"], 0)
                for key in STAT_KEYS:
                    self.assertIsNone(data[key], key)

    def test_defaults_to_a_valid_day_and_hour(self):
        response = self.get(**{"from": 161})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn(data["day"], range(7))
        self.assertIn(data["hour"], range(24))

    def test_missing_or_invalid_parameters_return_400(self):
        cases = (
            {"day": 0, "hour": 8},                       # no from
            {"from": "", "day": 0, "hour": 8},
            {"from": "abc", "day": 0, "hour": 8},
            {"from": 999, "day": 0, "hour": 8},          # unknown zone
            {"from": 161, "to": "abc", "day": 0, "hour": 8},
            {"from": 161, "to": 999, "day": 0, "hour": 8},
            {"from": 161, "day": 7, "hour": 8},
            {"from": 161, "day": -1, "hour": 8},
            {"from": 161, "day": "mon", "hour": 8},
            {"from": 161, "day": 0, "hour": 24},
            {"from": 161, "day": 0, "hour": "x"},
        )
        for params in cases:
            with self.subTest(params=params):
                response = self.get(**params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_post_not_allowed(self):
        response = self.client.post(reverse("zones:routes_api"))

        self.assertEqual(response.status_code, 405)
