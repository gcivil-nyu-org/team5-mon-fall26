"""US24 #71: Submit a fare report."""

import re
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from reports import forms as report_forms
from reports.admin import FareReportAdmin
from reports.models import FareReport
from reports.review import review_status, start_of_today
from zones.models import RouteHourStats, Zone
from zones.views import NYC_TZ

PASSWORD = "a-strong-test-password-24"


def local_input(moment):
    """A datetime-local value, as the browser sends it (New York time)."""
    return moment.astimezone(NYC_TZ).strftime("%Y-%m-%dT%H:%M")


class FareReportTestData(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.user = users.create_user("alex@example.com", password=PASSWORD)
        cls.other = users.create_user("other@example.com")
        cls.midtown = Zone.objects.create(
            zone_id=161, name="Midtown Center", borough="Manhattan"
        )
        cls.ues = Zone.objects.create(
            zone_id=237, name="Upper East Side South", borough="Manhattan"
        )
        cls.jfk = Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")
        # In the zone table but not on the map (no shape).
        cls.unknown = Zone.objects.create(
            zone_id=264, name="Unknown", borough="Unknown"
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("reports:report_fare")
        # Two days ago, on the hour, in New York time.
        self.ride = (timezone.now() - timedelta(days=2)).astimezone(NYC_TZ)
        self.ride = self.ride.replace(minute=0, second=0, microsecond=0)
        # Midtown → UES averages $20.00 at the ride's day and hour.
        RouteHourStats.objects.create(
            pickup_zone=self.midtown,
            dropoff_zone=self.ues,
            day_of_week=self.ride.weekday(),
            hour=self.ride.hour,
            trip_count=50,
            avg_duration_min=12.0,
            fare_min=Decimal("9.00"),
            fare_avg=Decimal("20.00"),
            fare_max=Decimal("60.00"),
        )
        self.data = {
            "pickup_zone": 161,
            "dropoff_zone": 237,
            "ride_at": local_input(self.ride),
            "taxi_fare": "21.50",
            "rideshare_service": "",
            "rideshare_quote": "",
        }

    def make_report(self, user=None, **fields):
        values = {
            "user": user or self.user,
            "pickup_zone": self.midtown,
            "dropoff_zone": self.ues,
            "ride_at": self.ride,
            "taxi_fare": Decimal("20.00"),
        }
        values.update(fields)
        return FareReport.objects.create(**values)

    def post(self, **changes):
        return self.client.post(self.url, {**self.data, **changes})


class SubmitFareReportTests(FareReportTestData):
    def test_url(self):
        self.assertEqual(self.url, "/reports/new/")

    def test_signed_in_user_can_submit_a_report_and_it_is_saved(self):
        self.data["user"] = self.other.pk
        self.data["status"] = FareReport.HELD
        response = self.post(rideshare_service="uber", rideshare_quote="27.40")
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        report = FareReport.objects.get()
        self.assertEqual(report.user, self.user)
        self.assertEqual(report.pickup_zone, self.midtown)
        self.assertEqual(report.dropoff_zone, self.ues)
        self.assertEqual(report.ride_at, self.ride)
        self.assertEqual(report.taxi_fare, Decimal("21.50"))
        self.assertEqual(report.rideshare_service, "uber")
        self.assertEqual(report.rideshare_quote, Decimal("27.40"))
        self.assertEqual(report.status, FareReport.VISIBLE)
        self.assertIsNotNone(report.created_at)

        page = self.client.get(response.url)
        self.assertContains(page, "Thanks! Your fare report was saved.")
        self.assertNotContains(page, "checked before other riders see it")

    def test_rideshare_fields_are_optional(self):
        self.post()
        report = FareReport.objects.get()
        self.assertEqual(report.rideshare_service, "")
        self.assertIsNone(report.rideshare_quote)

    def test_ride_time_is_read_as_new_york_time(self):
        # 2 days ago at 08:30 New York time, whatever the server's TIME_ZONE.
        ride = self.ride.replace(hour=8, minute=30)
        self.post(ride_at=ride.strftime("%Y-%m-%dT%H:%M"))
        saved = FareReport.objects.get().ride_at.astimezone(NYC_TZ)
        self.assertEqual((saved.hour, saved.minute), (8, 30))

    def test_success_keeps_the_zones_in_the_address(self):
        response = self.client.post(f"{self.url}?from=161&to=237", self.data)
        self.assertRedirects(
            response, f"{self.url}?from=161&to=237", fetch_redirect_response=False
        )

    def test_another_route_is_saved_as_given(self):
        self.post(pickup_zone=237, dropoff_zone=132)
        report = FareReport.objects.get()
        self.assertEqual(
            (report.pickup_zone, report.dropoff_zone), (self.ues, self.jfk)
        )

    def test_same_pickup_and_dropoff_zone_is_allowed(self):
        self.post(dropoff_zone=161)
        self.assertEqual(FareReport.objects.get().dropoff_zone, self.midtown)

    def test_zones_must_be_on_the_map(self):
        for changes in (
            {"pickup_zone": 264},
            {"dropoff_zone": 999},
            {"pickup_zone": ""},
        ):
            with self.subTest(changes=changes):
                response = self.post(**changes)
                self.assertEqual(response.status_code, 200)
        self.assertFalse(FareReport.objects.exists())


class ValidationTests(FareReportTestData):
    def assert_rejected(self, changes, message):
        response = self.post(**changes)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, escape(message))
        self.assertFalse(FareReport.objects.exists())

    def test_fare_of_zero_or_less_is_rejected(self):
        for fare in ("0", "0.00", "-5"):
            with self.subTest(fare=fare):
                self.assert_rejected({"taxi_fare": fare}, "Enter a taxi fare above $0.")

    def test_fare_over_500_is_rejected_and_500_is_allowed(self):
        self.assert_rejected(
            {"taxi_fare": "500.01"}, "Enter a taxi fare of $500 or less."
        )
        self.post(taxi_fare="500")
        self.assertEqual(FareReport.objects.get().taxi_fare, Decimal("500.00"))

    def test_missing_or_non_numeric_fare_is_rejected(self):
        for fare in ("", "abc"):
            with self.subTest(fare=fare):
                response = self.post(taxi_fare=fare)
                self.assertEqual(response.status_code, 200)
        self.assertFalse(FareReport.objects.exists())

    def test_quote_limits_match_the_taxi_fare(self):
        self.assert_rejected(
            {"rideshare_service": "lyft", "rideshare_quote": "0"},
            "Enter a rideshare quote above $0.",
        )
        self.assert_rejected(
            {"rideshare_service": "lyft", "rideshare_quote": "501"},
            "Enter a rideshare quote of $500 or less.",
        )

    def test_quote_without_a_service_is_rejected(self):
        self.assert_rejected(
            {"rideshare_quote": "25"},
            "Choose the rideshare service that gave this quote.",
        )

    def test_service_without_a_quote_is_rejected(self):
        self.assert_rejected(
            {"rideshare_service": "uber"},
            "Enter the price the rideshare service quoted.",
        )

    def test_unknown_service_is_rejected(self):
        response = self.post(rideshare_service="taxi", rideshare_quote="25")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FareReport.objects.exists())

    def test_future_ride_time_is_rejected(self):
        future = timezone.now() + timedelta(hours=2)
        self.assert_rejected(
            {"ride_at": local_input(future)}, "The ride time can't be in the future."
        )

    def test_ride_more_than_30_days_ago_is_rejected(self):
        old = timezone.now() - timedelta(days=30, hours=1)
        self.assert_rejected(
            {"ride_at": local_input(old)}, "Report rides from the last 30 days only."
        )

    def test_ride_just_inside_30_days_is_allowed(self):
        recent = timezone.now() - timedelta(days=29, hours=23)
        self.post(ride_at=local_input(recent))
        self.assertTrue(FareReport.objects.exists())

    def test_missing_or_bad_ride_time_is_rejected(self):
        for value in ("", "yesterday"):
            with self.subTest(value=value):
                response = self.post(ride_at=value)
                self.assertEqual(response.status_code, 200)
        self.assertFalse(FareReport.objects.exists())


class ReviewTests(FareReportTestData):
    def status_for(self, fare, pickup=161, dropoff=237, ride=None):
        return review_status(pickup, dropoff, ride or self.ride, Decimal(fare))

    def test_fare_near_the_average_is_visible(self):
        for fare in ("6.67", "20.00", "60.00"):
            with self.subTest(fare=fare):
                self.assertEqual(self.status_for(fare), FareReport.VISIBLE)

    def test_fare_below_a_third_or_above_3_times_is_held(self):
        for fare in ("6.66", "1.00", "60.01", "300.00"):
            with self.subTest(fare=fare):
                self.assertEqual(self.status_for(fare), FareReport.HELD)

    def test_route_with_too_few_trips_is_published(self):
        RouteHourStats.objects.update(trip_count=4)
        self.assertEqual(self.status_for("300.00"), FareReport.VISIBLE)

    def test_route_or_hour_with_no_trips_is_published(self):
        self.assertEqual(self.status_for("300.00", dropoff=132), FareReport.VISIBLE)
        other_hour = self.ride + timedelta(hours=1)
        self.assertEqual(self.status_for("300.00", ride=other_hour), FareReport.VISIBLE)

    def test_day_and_hour_come_from_new_york_time(self):
        # The same moment, given in UTC, still matches the New York hour.
        utc = self.ride.astimezone(timezone.get_fixed_timezone(0))
        self.assertEqual(self.status_for("300.00", ride=utc), FareReport.HELD)

    def test_outlier_is_saved_held_and_not_public(self):
        response = self.post(taxi_fare="150.00")
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        report = FareReport.objects.get()
        self.assertEqual(report.status, FareReport.HELD)
        self.assertEqual(report.get_status_display(), "Held for review")
        self.assertNotIn(report, FareReport.objects.public())
        page = self.client.get(response.url)
        self.assertContains(page, "checked before other riders see it")

    def test_public_reports_leave_out_held_ones(self):
        visible = self.make_report()
        self.make_report(status=FareReport.HELD)
        self.assertQuerySetEqual(FareReport.objects.public(), [visible])


class DailyLimitTests(FareReportTestData):
    LIMIT = "You can submit up to 10 fare reports a day. Try again tomorrow."

    def test_the_11th_report_in_one_day_is_rejected(self):
        for _ in range(9):
            self.make_report()
        self.post()
        self.assertEqual(FareReport.objects.count(), 10)
        response = self.post()
        self.assertContains(response, self.LIMIT)
        self.assertEqual(FareReport.objects.count(), 10)

    def test_held_reports_count_too(self):
        for _ in range(10):
            self.make_report(status=FareReport.HELD)
        self.assertContains(self.post(), self.LIMIT)

    def test_reports_from_yesterday_and_other_users_do_not_count(self):
        for _ in range(10):
            self.make_report(user=self.other)
        for _ in range(10):
            self.make_report()
        FareReport.objects.filter(user=self.user).update(
            created_at=start_of_today(timezone.now()) - timedelta(minutes=1)
        )
        self.assertRedirects(self.post(), self.url, fetch_redirect_response=False)

    def test_the_day_starts_at_midnight_in_new_york(self):
        # 03:30 UTC on Nov 5 is still Nov 4 in New York (UTC-5).
        now = datetime(2026, 11, 5, 3, 30, tzinfo=timezone.get_fixed_timezone(0))
        start = start_of_today(now)
        self.assertEqual(start, datetime(2026, 11, 4, tzinfo=NYC_TZ))
        self.assertEqual(start.astimezone(NYC_TZ).hour, 0)


class GuestTests(FareReportTestData):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_guest_sees_a_sign_in_prompt_in_place_of_the_form(self):
        response = self.client.get(f"{self.url}?from=161&to=237")
        self.assertContains(response, "Sign in to report a fare")
        self.assertNotContains(response, "<form")
        signin = reverse("accounts:signin")
        self.assertContains(
            response,
            f'href="{signin}?next=%2Freports%2Fnew%2F%3Ffrom%3D161%26to%3D237"',
        )

    def test_guest_post_saves_nothing(self):
        response = self.post()
        self.assertContains(response, "Sign in to report a fare")
        self.assertFalse(FareReport.objects.exists())

    def test_sign_in_comes_back_to_the_form(self):
        signin = reverse("accounts:signin")
        response = self.client.post(
            f"{signin}?next=/reports/new/%3Ffrom%3D161%26to%3D237",
            {"username": "alex@example.com", "password": PASSWORD},
        )
        self.assertRedirects(
            response, f"{self.url}?from=161&to=237", fetch_redirect_response=False
        )


class FormPageTests(FareReportTestData):
    def test_zones_from_the_trip_summary_are_filled_in(self):
        response = self.client.get(f"{self.url}?from=161&to=237")
        form = response.context["form"]
        self.assertEqual(form["pickup_zone"].value(), 161)
        self.assertEqual(form["dropoff_zone"].value(), 237)
        self.assertContains(response, '<option value="161" selected>')
        self.assertContains(response, '<option value="237" selected>')

    def test_bad_zones_in_the_address_are_left_empty(self):
        response = self.client.get(f"{self.url}?from=abc&to=0")
        form = response.context["form"]
        self.assertIsNone(form["pickup_zone"].value())
        self.assertIsNone(form["dropoff_zone"].value())

    def test_only_zones_on_the_map_are_offered(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Midtown Center (Manhattan)")
        self.assertNotContains(response, "Unknown (Unknown)")

    def test_ride_time_starts_at_now_in_new_york_time(self):
        before = timezone.now().astimezone(NYC_TZ).replace(second=0, microsecond=0)
        response = self.client.get(self.url)
        after = timezone.now().astimezone(NYC_TZ)
        self.assertContains(response, 'type="datetime-local"')
        shown = re.search(r'name="ride_at" value="([^"]+)"', response.text).group(1)
        shown = datetime.strptime(shown, "%Y-%m-%dT%H:%M").replace(tzinfo=NYC_TZ)
        self.assertTrue(before <= shown <= after)

    def test_form_asks_for_the_fare_before_tip_and_says_so(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Taxi fare before tip ($)")
        self.assertContains(response, "minus the tip")
        self.assertContains(response, "never addresses")

    def test_service_choices_are_uber_and_lyft(self):
        choices = (
            report_forms.FareReportForm(self.user).fields["rideshare_service"].choices
        )
        self.assertEqual(
            list(choices), [("", "None"), ("uber", "Uber"), ("lyft", "Lyft")]
        )

    def test_form_has_csrf_protection(self):
        response = self.client.get(self.url)
        self.assertContains(response, "csrfmiddlewaretoken")
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.url, self.data).status_code, 403)
        self.assertFalse(FareReport.objects.exists())

    def test_other_methods_are_not_allowed(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)

    def test_no_address_fields_are_stored(self):
        names = {field.name for field in FareReport._meta.get_fields()}
        self.assertEqual(
            names,
            {
                "id",
                "user",
                "pickup_zone",
                "dropoff_zone",
                "ride_at",
                "taxi_fare",
                "rideshare_service",
                "rideshare_quote",
                "status",
                "created_at",
            },
        )


class MapLinkTests(FareReportTestData):
    def test_trip_summary_has_report_a_fare_for_signed_in_users(self):
        response = self.client.get(reverse("zones:map"))
        self.assertContains(response, 'id="report-fare-link"')
        self.assertContains(response, ">Report a fare</a>")
        self.assertNotContains(response, "data-signin=")
        self.assertContains(response, "reports/js/report-fare-link.js")

    def test_guests_see_sign_in_to_report_a_fare(self):
        response = Client().get(reverse("zones:map"))
        self.assertContains(response, ">Sign in to report a fare</a>")
        self.assertContains(response, f'data-signin="{reverse("accounts:signin")}"')


class DatabaseTests(FareReportTestData):
    def assert_database_rejects(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_report(**fields)

    def test_database_rejects_fares_out_of_range(self):
        self.assert_database_rejects(taxi_fare=Decimal("0"))
        self.assert_database_rejects(taxi_fare=Decimal("500.01"))
        self.assert_database_rejects(
            rideshare_service="uber", rideshare_quote=Decimal("0")
        )

    def test_database_rejects_a_quote_without_a_service_and_the_other_way(self):
        self.assert_database_rejects(rideshare_quote=Decimal("20"))
        self.assert_database_rejects(rideshare_service="lyft")

    def test_new_reports_are_visible_by_default(self):
        self.assertEqual(self.make_report().status, FareReport.VISIBLE)

    def test_newest_first(self):
        first = self.make_report()
        second = self.make_report()
        self.assertEqual(list(FareReport.objects.all()), [second, first])

    def test_str(self):
        report = self.make_report(status=FareReport.HELD)
        self.assertEqual(
            str(report),
            "Midtown Center → Upper East Side South, $20.00 (Held for review)",
        )

    def test_deleting_the_user_deletes_their_reports(self):
        self.make_report()
        kept = self.make_report(user=self.other)
        self.user.delete()
        self.assertEqual(list(FareReport.objects.all()), [kept])

    def test_delete_my_account_page_deletes_their_reports(self):
        self.make_report()
        response = self.client.post(reverse("accounts:delete"), {"password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(FareReport.objects.exists())


class AdminTests(FareReportTestData):
    def test_registered_with_status_list_and_filter(self):
        model_admin = admin.site._registry[FareReport]
        self.assertIsInstance(model_admin, FareReportAdmin)
        self.assertIn("status", model_admin.list_display)
        self.assertIn("status", model_admin.list_filter)

    def test_staff_can_filter_held_reports(self):
        self.make_report(status=FareReport.HELD, taxi_fare=Decimal("150.00"))
        self.make_report(taxi_fare=Decimal("21.00"))
        staff = get_user_model().objects.create_superuser("admin@example.com")
        self.client.force_login(staff)
        url = reverse("admin:reports_farereport_changelist")
        response = self.client.get(url, {"status__exact": FareReport.HELD})
        self.assertContains(response, "150.00")
        self.assertNotContains(response, "21.00")


class ClockTests(FareReportTestData):
    def test_form_uses_the_time_it_is_given(self):
        later = timezone.now() + timedelta(days=10)
        form = report_forms.FareReportForm(self.user, self.data, now=later)
        self.assertTrue(form.is_valid(), form.errors)
        with patch("reports.forms.timezone.now", return_value=later):
            form = report_forms.FareReportForm(self.user, self.data)
            self.assertEqual(form.now, later)
