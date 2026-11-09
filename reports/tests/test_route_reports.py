"""US26 #73: public recent fares for a selected route."""

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from reports.models import FareReport
from zones.models import Zone


class RouteReportsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rider@example.com")
        cls.pickup = Zone.objects.create(
            zone_id=161, name="Midtown Center", borough="Manhattan"
        )
        cls.dropoff = Zone.objects.create(
            zone_id=237, name="Upper East Side South", borough="Manhattan"
        )
        cls.other = Zone.objects.create(
            zone_id=132, name="JFK Airport", borough="Queens"
        )

    def setUp(self):
        self.now = datetime(2026, 11, 5, 12, tzinfo=dt_timezone.utc)
        self.url = reverse("reports:route_reports")

    def make_report(self, **changes):
        values = {
            "user": self.user,
            "pickup_zone": self.pickup,
            "dropoff_zone": self.dropoff,
            "ride_at": self.now - timedelta(days=2),
            "taxi_fare": Decimal("20.00"),
        }
        values.update(changes)
        return FareReport.objects.create(**values)

    def get_reports(self, **params):
        with patch("reports.views.timezone.now", return_value=self.now):
            return self.client.get(
                self.url,
                {"from": self.pickup.zone_id, "to": self.dropoff.zone_id, **params},
            )

    def test_guest_sees_medians_quotes_and_nyc_ride_time_without_identity(self):
        fares = ["10.00", "10.01", "10.02", "10.03"]
        for index, fare in enumerate(fares):
            changes = {
                "ride_at": self.now - timedelta(days=4 - index),
                "taxi_fare": Decimal(fare),
            }
            if index < 2:
                changes.update(
                    rideshare_service="uber" if index == 0 else "lyft",
                    rideshare_quote=Decimal("20.00" if index == 0 else "20.01"),
                )
            self.make_report(**changes)
        latest = self.make_report(
            ride_at=self.now - timedelta(hours=8, minutes=45),
            taxi_fare=Decimal("10.04"),
        )

        response = self.get_reports()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["enough_data"])
        self.assertEqual(data["report_count"], 5)
        self.assertEqual(data["median_taxi_fare"], "10.02")
        self.assertEqual(data["rideshare_quote_count"], 2)
        self.assertEqual(data["median_rideshare_quote"], "20.01")
        recent = data["recent_reports"]
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[0]["taxi_fare"], str(latest.taxi_fare))
        self.assertEqual(recent[0]["ride_day"], "2026-11-04")
        self.assertEqual(recent[0]["ride_hour"], 22)
        self.assertEqual(
            set(recent[0]),
            {
                "ride_day",
                "ride_hour",
                "taxi_fare",
                "rideshare_service",
                "rideshare_quote",
            },
        )
        self.assertNotIn("rider@example.com", response.content.decode())

    def test_fewer_than_three_hides_medians_and_recent_reports(self):
        self.make_report()
        self.make_report(taxi_fare=Decimal("30.00"))
        data = self.get_reports().json()
        self.assertFalse(data["enough_data"])
        self.assertEqual(data["report_count"], 2)
        self.assertIsNone(data["median_taxi_fare"])
        self.assertIsNone(data["median_rideshare_quote"])
        self.assertEqual(data["recent_reports"], [])

    def test_only_visible_recent_reports_on_exact_route_are_counted(self):
        self.make_report(ride_at=self.now - timedelta(days=90))
        self.make_report(ride_at=self.now - timedelta(days=1))
        self.make_report(status=FareReport.HELD)
        self.make_report(ride_at=self.now - timedelta(days=90, seconds=1))
        self.make_report(ride_at=self.now + timedelta(minutes=1))
        self.make_report(dropoff_zone=self.other)
        self.make_report(pickup_zone=self.other)
        deleted = self.make_report()
        deleted.delete()

        data = self.get_reports().json()
        self.assertEqual(data["report_count"], 2)
        self.assertFalse(data["enough_data"])
        self.make_report(ride_at=self.now - timedelta(days=3))
        self.assertEqual(self.get_reports().json()["report_count"], 3)

    def test_recent_list_has_at_most_five_rides_ordered_by_ride_time(self):
        for days in range(6, 0, -1):
            self.make_report(
                ride_at=self.now - timedelta(days=days),
                taxi_fare=Decimal(days),
            )
        recent = self.get_reports().json()["recent_reports"]
        self.assertEqual(len(recent), 5)
        self.assertEqual(
            [item["taxi_fare"] for item in recent],
            ["1.00", "2.00", "3.00", "4.00", "5.00"],
        )

    def test_no_quotes_has_null_quote_median(self):
        for _ in range(3):
            self.make_report()
        data = self.get_reports().json()
        self.assertEqual(data["rideshare_quote_count"], 0)
        self.assertIsNone(data["median_rideshare_quote"])

    def test_zone_parameters_and_method_are_validated(self):
        for params in (
            {},
            {"from": 161},
            {"from": "bad", "to": 237},
            {"from": 161, "to": 999},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)
        self.assertEqual(self.client.post(self.url).status_code, 405)
