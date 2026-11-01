"""US16 #45: Leave by, cheapest in the next 3 hours."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from routes.planning import cheapest_in_window
from zones.models import RouteHourStats, Zone

FRIDAY, SATURDAY, SUNDAY, MONDAY = 4, 5, 6, 0


@override_settings(MIN_TRIP_COUNT=5)
class CheapestInWindowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pickup = Zone.objects.create(zone_id=1, name="Office", borough="Manhattan")
        cls.dropoff = Zone.objects.create(zone_id=2, name="Home", borough="Queens")

    def row(self, day, hour, fare, duration=20, count=10, dropoff=None):
        return RouteHourStats.objects.create(
            pickup_zone=self.pickup,
            dropoff_zone=dropoff or self.dropoff,
            day_of_week=day,
            hour=hour,
            trip_count=count,
            avg_duration_min=duration,
            fare_min=Decimal("5.00"),
            fare_avg=Decimal(fare),
            fare_max=Decimal("60.00"),
        )

    def plan(self, day, hour, minute=0):
        return cheapest_in_window(1, 2, day, hour, minute)

    def test_lists_three_hours_and_picks_the_cheapest(self):
        self.row(MONDAY, 8, "20.00")
        self.row(MONDAY, 9, "15.50", duration=25)
        self.row(MONDAY, 10, "18.00")
        result = self.plan(MONDAY, 8)
        self.assertEqual(
            [(h["day"], h["hour"]) for h in result["hours"]], [(0, 8), (0, 9), (0, 10)]
        )
        self.assertEqual(
            [h["fare_avg"] for h in result["hours"]],
            [Decimal("20.00"), Decimal("15.50"), Decimal("18.00")],
        )
        self.assertEqual(result["cheapest"], 1)
        self.assertEqual(result["fare_avg"], Decimal("15.50"))

    def test_leaves_at_the_start_of_the_cheapest_hour(self):
        self.row(MONDAY, 8, "20.00")
        self.row(MONDAY, 9, "15.50", duration=25)
        result = self.plan(MONDAY, 8, 30)
        self.assertEqual((result["leave_day"], result["leave"]), (MONDAY, "09:00"))
        self.assertEqual((result["arrive_day"], result["arrive"]), (MONDAY, "09:25"))
        self.assertEqual(result["avg_duration_min"], 25)

    def test_leaves_at_the_start_time_when_the_first_hour_is_cheapest(self):
        self.row(MONDAY, 8, "12.00", duration=18)
        self.row(MONDAY, 9, "15.50")
        result = self.plan(MONDAY, 8, 37)
        self.assertEqual(result["cheapest"], 0)
        self.assertEqual((result["leave_day"], result["leave"]), (MONDAY, "08:37"))
        self.assertEqual((result["arrive_day"], result["arrive"]), (MONDAY, "08:55"))

    def test_tie_goes_to_the_earlier_hour(self):
        self.row(MONDAY, 8, "20.00")
        self.row(MONDAY, 9, "14.00")
        self.row(MONDAY, 10, "14.00")
        self.assertEqual(self.plan(MONDAY, 8)["cheapest"], 1)

    def test_window_passing_midnight_uses_the_next_day(self):
        # Friday 22:00 covers Friday 22:00, Friday 23:00 and Saturday 00:00.
        self.row(FRIDAY, 22, "30.00")
        self.row(FRIDAY, 23, "28.00")
        self.row(SATURDAY, 0, "21.00", duration=40)
        self.row(FRIDAY, 0, "1.00")  # same hour, wrong day: must be ignored
        result = self.plan(FRIDAY, 22)
        self.assertEqual(
            [(h["day"], h["hour"]) for h in result["hours"]],
            [(FRIDAY, 22), (FRIDAY, 23), (SATURDAY, 0)],
        )
        self.assertEqual(result["cheapest"], 2)
        self.assertEqual((result["leave_day"], result["leave"]), (SATURDAY, "00:00"))
        self.assertEqual((result["arrive_day"], result["arrive"]), (SATURDAY, "00:40"))

    def test_sunday_night_wraps_to_monday(self):
        self.row(SUNDAY, 23, "30.00", duration=50)
        self.row(MONDAY, 0, "35.00")
        result = self.plan(SUNDAY, 23, 45)
        self.assertEqual(
            [(h["day"], h["hour"]) for h in result["hours"]],
            [(SUNDAY, 23), (MONDAY, 0), (MONDAY, 1)],
        )
        self.assertEqual(result["cheapest"], 0)
        self.assertEqual((result["arrive_day"], result["arrive"]), (MONDAY, "00:35"))

    def test_hours_with_too_few_trips_are_marked_and_not_compared(self):
        self.row(MONDAY, 8, "1.00", count=4)  # cheapest, but only 4 trips
        self.row(MONDAY, 9, "15.00")
        result = self.plan(MONDAY, 8)
        first = result["hours"][0]
        self.assertFalse(first["enough_data"])
        self.assertEqual(first["trip_count"], 4)
        self.assertIsNone(first["fare_avg"])
        self.assertFalse(result["hours"][2]["enough_data"])  # no row at all
        self.assertEqual(result["cheapest"], 1)

    def test_no_hour_with_enough_trips(self):
        self.row(MONDAY, 8, "10.00", count=2)
        result = self.plan(MONDAY, 8)
        self.assertFalse(result["enough_data"])
        self.assertIsNone(result["cheapest"])
        self.assertIsNone(result["leave"])
        self.assertEqual(len(result["hours"]), 3)


class CheapestApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pickup = Zone.objects.create(zone_id=1, name="Office", borough="Manhattan")
        cls.dropoff = Zone.objects.create(zone_id=2, name="Home", borough="Queens")
        for hour, fare in [(22, "30.00"), (23, "28.00")]:
            RouteHourStats.objects.create(
                pickup_zone=cls.pickup,
                dropoff_zone=cls.dropoff,
                day_of_week=FRIDAY,
                hour=hour,
                trip_count=10,
                avg_duration_min=30,
                fare_min=Decimal("5.00"),
                fare_avg=Decimal(fare),
                fare_max=Decimal("60.00"),
            )

    def get(self, **overrides):
        params = {"from": 1, "to": 2, "day": FRIDAY, "start": "22:00"}
        params.update(overrides)
        return self.client.get(reverse("routes:cheapest_api"), params)

    def test_returns_the_three_hours_and_the_suggestion(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            (data["from"], data["to"], data["day"], data["start"]),
            (1, 2, FRIDAY, "22:00"),
        )
        self.assertTrue(data["enough_data"])
        self.assertEqual(data["cheapest"], 1)
        self.assertEqual(
            [h["fare_avg"] for h in data["hours"]], ["30.00", "28.00", None]
        )
        self.assertEqual((data["leave_day"], data["leave"]), (FRIDAY, "23:00"))
        self.assertEqual((data["arrive_day"], data["arrive"]), (FRIDAY, "23:30"))

    def test_now_can_send_any_minute(self):
        self.assertEqual(self.get(start="22:37").status_code, 200)

    def test_invalid_parameters_return_400(self):
        for params in (
            {"from": ""},
            {"from": 999},
            {"to": ""},
            {"to": 999},
            {"day": -1},
            {"day": 7},
            {"day": "Friday"},
            {"start": ""},
            {"start": "9:00"},
            {"start": "24:00"},
            {"start": "22:60"},
            {"start": "22:00:00"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.get(**params).status_code, 400)

    def test_endpoint_is_public_and_get_only(self):
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(
            self.client.post(reverse("routes:cheapest_api")).status_code, 405
        )

    def test_map_has_cheapest_option_now_button_and_script(self):
        page = self.client.get(reverse("zones:map"))
        self.assertContains(page, "Cheapest in the next 3 hours")
        self.assertContains(page, 'id="cheapest-form"')
        self.assertContains(page, 'id="cheapest-now"')
        self.assertContains(
            page, 'id="cheapest-start" name="start" type="time" step="900"'
        )
        self.assertContains(page, "routes/js/cheapest.js")
        self.assertContains(
            page, "Estimate from past trips (March to May 2026), not a guarantee."
        )
