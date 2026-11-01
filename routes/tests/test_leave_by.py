from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from zones.models import RouteHourStats, Zone


class LeaveByApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pickup = Zone.objects.create(zone_id=1, name="Office", borough="Manhattan")
        cls.dropoff = Zone.objects.create(zone_id=2, name="Home", borough="Queens")

    def row(self, day, hour, duration, fare="12.34", count=10, dropoff=None):
        return RouteHourStats.objects.create(
            pickup_zone=self.pickup,
            dropoff_zone=dropoff or self.dropoff,
            day_of_week=day,
            hour=hour,
            trip_count=count,
            avg_duration_min=duration,
            fare_min=Decimal("5.00"),
            fare_avg=Decimal(fare),
            fare_max=Decimal("25.00"),
        )

    def get(self, **overrides):
        params = {"from": 1, "to": 2, "day": 0, "arrive": "09:15"}
        params.update(overrides)
        return self.client.get(reverse("routes:leave_by_api"), params)

    def test_recalculates_from_departure_hour_and_rounds_down(self):
        self.row(0, 9, 20, fare="99.00")
        self.row(0, 8, 35, fare="12.34")
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "from": 1,
                "to": 2,
                "day": 0,
                "arrive": "09:15",
                "enough_data": True,
                "leave_day": 0,
                "leave": "08:30",
                "trip_count": 10,
                "avg_duration_min": 35.0,
                "fare_avg": "12.34",
            },
        )

    def test_early_arrival_uses_previous_day_and_departure_hour_fare(self):
        self.row(1, 0, 50, fare="99.00")
        self.row(0, 23, 45, fare="18.75")
        data = self.get(day=1, arrive="00:30").json()
        self.assertTrue(data["enough_data"])
        self.assertEqual((data["leave_day"], data["leave"]), (0, "23:45"))
        self.assertEqual(data["fare_avg"], "18.75")

    def test_sunday_to_monday_wraps_week(self):
        self.row(0, 0, 40)
        self.row(6, 23, 35)
        data = self.get(day=0, arrive="00:15").json()
        self.assertEqual((data["leave_day"], data["leave"]), (6, "23:30"))

    def test_same_zone_trip_is_allowed(self):
        self.row(0, 9, 10, dropoff=self.pickup)
        data = self.get(to=1).json()
        self.assertEqual((data["leave_day"], data["leave"]), (0, "09:00"))

    def test_missing_arrival_or_departure_hour_returns_not_enough_data(self):
        no_arrival = self.get().json()
        self.assertFalse(no_arrival["enough_data"])
        self.assertIsNone(no_arrival["leave"])
        self.assertEqual(no_arrival["trip_count"], 0)
        self.row(0, 9, 20)
        no_departure = self.get().json()
        self.assertFalse(no_departure["enough_data"])
        self.assertIsNone(no_departure["fare_avg"])
        self.assertEqual(no_departure["trip_count"], 0)

    def test_sparse_departure_hour_is_not_enough_data(self):
        self.row(0, 9, 20)
        self.row(0, 8, 35, count=4)
        data = self.get().json()
        self.assertFalse(data["enough_data"])
        self.assertEqual(data["trip_count"], 4)
        self.assertIsNone(data["avg_duration_min"])

    def test_invalid_parameters_return_400(self):
        for params in (
            {"from": ""},
            {"from": 999},
            {"to": ""},
            {"to": 999},
            {"day": -1},
            {"day": 7},
            {"day": "Monday"},
            {"arrive": ""},
            {"arrive": "9:15"},
            {"arrive": "24:00"},
            {"arrive": "09:10"},
            {"arrive": "09:00:00"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.get(**params).status_code, 400)

    def test_endpoint_is_public_and_get_only(self):
        self.row(0, 9, 10)
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(
            self.client.post(reverse("routes:leave_by_api")).status_code, 405
        )

    def test_map_has_arrive_by_form_and_script(self):
        page = self.client.get(reverse("zones:map"))
        self.assertContains(page, 'id="leave-by-form"')
        self.assertContains(page, 'step="900"')
        self.assertContains(page, "routes/js/leave-by.js")
        self.assertContains(page, "Estimate from past trips (March to May 2026)")
