"""US25 #72: View, edit and delete my fare reports."""

from datetime import timedelta
from decimal import Decimal

from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from reports.models import FareReport
from reports.tests.test_fare_reports import FareReportTestData, local_input
from zones.views import NYC_TZ


class MyFareReportsTests(FareReportTestData):
    def setUp(self):
        super().setUp()
        self.url = reverse("reports:my_reports")

    def test_url(self):
        self.assertEqual(self.url, "/reports/")

    def test_lists_all_my_reports_with_status_including_held_ones(self):
        self.make_report(taxi_fare=Decimal("21.50"))
        self.make_report(
            taxi_fare=Decimal("150.00"),
            status=FareReport.HELD,
            rideshare_service="lyft",
            rideshare_quote=Decimal("31.25"),
        )
        response = self.client.get(self.url)
        self.assertContains(response, "Midtown Center → Upper East Side South", 2)
        self.assertContains(response, "$21.50")
        self.assertContains(response, "$150.00")
        self.assertContains(response, "Lyft $31.25")
        self.assertContains(response, ">Visible<")
        self.assertContains(response, ">Held for review<")

    def test_shows_the_ride_date_and_time_in_new_york_time(self):
        self.make_report()
        response = self.client.get(self.url)
        self.assertContains(response, self.ride.strftime("%b %-d, %Y, %-I:%M %p"))

    def test_newest_first(self):
        older = self.make_report(taxi_fare=Decimal("11.00"))
        newer = self.make_report(taxi_fare=Decimal("22.00"))
        response = self.client.get(self.url)
        self.assertEqual(list(response.context["reports"]), [newer, older])
        text = response.content.decode()
        self.assertLess(text.index("$22.00"), text.index("$11.00"))

    def test_no_quote_shows_a_dash(self):
        self.make_report()
        self.assertContains(self.client.get(self.url), "<td>—</td>")

    def test_only_my_reports_are_listed(self):
        self.make_report(user=self.other, taxi_fare=Decimal("77.00"))
        response = self.client.get(self.url)
        self.assertNotContains(response, "$77.00")
        self.assertContains(response, "No fare reports yet.")

    def test_each_report_has_edit_and_delete(self):
        report = self.make_report()
        response = self.client.get(self.url)
        self.assertContains(response, reverse("reports:edit_report", args=[report.pk]))
        self.assertContains(
            response, reverse("reports:delete_report", args=[report.pk])
        )

    def test_links_to_my_fare_reports(self):
        self.assertContains(
            self.client.get(reverse("routes:my_routes")),
            f'<a href="{self.url}">Fare reports</a>',
        )
        self.assertContains(
            self.client.get(reverse("reports:report_fare")),
            f'<a href="{self.url}">My fare reports</a>',
        )


class EditFareReportTests(FareReportTestData):
    def setUp(self):
        super().setUp()
        self.report = self.make_report(
            taxi_fare=Decimal("21.50"),
            rideshare_service="uber",
            rideshare_quote=Decimal("27.40"),
        )
        self.edit_url = reverse("reports:edit_report", args=[self.report.pk])

    def edit(self, **changes):
        return self.client.post(self.edit_url, {**self.data, **changes})

    def test_url(self):
        self.assertEqual(self.edit_url, f"/reports/{self.report.pk}/edit/")

    def test_edit_form_starts_with_the_report(self):
        response = self.client.get(self.edit_url)
        form = response.context["form"]
        self.assertEqual(form["pickup_zone"].value(), 161)
        self.assertEqual(form["dropoff_zone"].value(), 237)
        self.assertEqual(form["taxi_fare"].value(), Decimal("21.50"))
        self.assertEqual(form["rideshare_service"].value(), "uber")
        self.assertContains(response, local_input(self.ride))
        self.assertContains(response, "Edit fare report")

    def test_editing_updates_the_report(self):
        response = self.edit(
            dropoff_zone=132,
            taxi_fare="18.00",
            rideshare_service="lyft",
            rideshare_quote="24.00",
        )
        self.assertRedirects(
            response, reverse("reports:my_reports"), fetch_redirect_response=False
        )
        self.report.refresh_from_db()
        self.assertEqual(self.report.dropoff_zone, self.jfk)
        self.assertEqual(self.report.taxi_fare, Decimal("18.00"))
        self.assertEqual(self.report.rideshare_service, "lyft")
        self.assertEqual(self.report.rideshare_quote, Decimal("24.00"))
        self.assertEqual(self.report.user, self.user)
        self.assertEqual(FareReport.objects.count(), 1)
        page = self.client.get(response.url)
        self.assertContains(page, "Fare report updated.")

    def test_removing_the_quote_clears_both_fields(self):
        self.edit()
        self.report.refresh_from_db()
        self.assertEqual(self.report.rideshare_service, "")
        self.assertIsNone(self.report.rideshare_quote)

    def test_editing_to_an_outlier_holds_the_report(self):
        response = self.edit(taxi_fare="150.00")
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, FareReport.HELD)
        self.assertNotIn(self.report, FareReport.objects.public())
        page = self.client.get(response.url)
        self.assertContains(page, "checked before other riders see it")

    def test_editing_back_to_a_normal_fare_makes_it_visible_again(self):
        FareReport.objects.filter(pk=self.report.pk).update(status=FareReport.HELD)
        self.edit(taxi_fare="19.00")
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, FareReport.VISIBLE)

    def test_check_uses_the_edited_route_and_time(self):
        # No history for Midtown → JFK, so even $300 is published.
        self.edit(dropoff_zone=132, taxi_fare="300.00")
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, FareReport.VISIBLE)
        # Back on Midtown → UES, an hour with no trips is published too.
        later = self.ride + timedelta(hours=1)
        self.edit(taxi_fare="300.00", ride_at=local_input(later))
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, FareReport.VISIBLE)
        # At the ride's own hour it is held.
        self.edit(taxi_fare="300.00")
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, FareReport.HELD)

    def test_same_validation_as_a_new_report(self):
        cases = [
            ({"taxi_fare": "0"}, "Enter a taxi fare above $0."),
            ({"taxi_fare": "500.01"}, "Enter a taxi fare of $500 or less."),
            (
                {"rideshare_service": "", "rideshare_quote": "20"},
                "Choose the rideshare service that gave this quote.",
            ),
            (
                {"rideshare_service": "lyft", "rideshare_quote": ""},
                "Enter the price the rideshare service quoted.",
            ),
            (
                {"ride_at": local_input(timezone.now() + timedelta(hours=1))},
                "The ride time can't be in the future.",
            ),
            (
                {"ride_at": local_input(timezone.now() - timedelta(days=31))},
                "Report rides from the last 30 days only.",
            ),
            ({"pickup_zone": 264}, "Select a valid choice."),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes):
                response = self.edit(**changes)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, escape(message))
        self.report.refresh_from_db()
        self.assertEqual(self.report.taxi_fare, Decimal("21.50"))

    def test_30_days_count_from_when_the_report_was_made(self):
        # Reported 20 days ago about a ride 25 days ago: still editable
        # with the same ride time, although that is now 45 days back.
        reported = timezone.now() - timedelta(days=20)
        ride = reported - timedelta(days=25)
        FareReport.objects.filter(pk=self.report.pk).update(
            created_at=reported, ride_at=ride
        )
        response = self.edit(ride_at=local_input(ride), taxi_fare="19.00")
        self.assertEqual(response.status_code, 302)
        too_old = reported - timedelta(days=31)
        response = self.edit(ride_at=local_input(too_old))
        self.assertContains(response, "Report rides from the last 30 days only.")

    def test_editing_does_not_count_against_the_daily_limit(self):
        for _ in range(9):
            self.make_report()
        self.assertEqual(FareReport.objects.count(), 10)
        response = self.edit(taxi_fare="19.00")
        self.assertEqual(response.status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.taxi_fare, Decimal("19.00"))

    def test_owner_and_status_cannot_be_set_by_the_request(self):
        self.edit(user=self.other.pk, status=FareReport.HELD)
        self.report.refresh_from_db()
        self.assertEqual(self.report.user, self.user)
        self.assertEqual(self.report.status, FareReport.VISIBLE)

    def test_edit_time_is_read_as_new_york_time(self):
        ride = self.ride.astimezone(NYC_TZ).replace(hour=7, minute=45)
        self.edit(ride_at=ride.strftime("%Y-%m-%dT%H:%M"))
        self.report.refresh_from_db()
        saved = self.report.ride_at.astimezone(NYC_TZ)
        self.assertEqual((saved.hour, saved.minute), (7, 45))


class DeleteFareReportTests(FareReportTestData):
    def setUp(self):
        super().setUp()
        self.report = self.make_report()
        self.delete_url = reverse("reports:delete_report", args=[self.report.pk])

    def test_url(self):
        self.assertEqual(self.delete_url, f"/reports/{self.report.pk}/delete/")

    def test_delete_asks_first(self):
        response = self.client.get(self.delete_url)
        self.assertContains(response, "Delete fare report?")
        self.assertContains(response, "Midtown Center → Upper East Side South")
        self.assertContains(response, "$20.00")
        self.assertTrue(FareReport.objects.filter(pk=self.report.pk).exists())

    def test_delete_removes_it_everywhere(self):
        kept = self.make_report()
        response = self.client.post(self.delete_url)
        self.assertRedirects(
            response, reverse("reports:my_reports"), fetch_redirect_response=False
        )
        self.assertFalse(FareReport.objects.filter(pk=self.report.pk).exists())
        self.assertQuerySetEqual(FareReport.objects.public(), [kept])
        page = self.client.get(response.url)
        self.assertContains(page, "Fare report deleted.")

    def test_held_reports_can_be_deleted_too(self):
        FareReport.objects.filter(pk=self.report.pk).update(status=FareReport.HELD)
        self.client.post(self.delete_url)
        self.assertFalse(FareReport.objects.exists())


class OwnershipTests(FareReportTestData):
    def setUp(self):
        super().setUp()
        self.theirs = self.make_report(user=self.other, taxi_fare=Decimal("33.00"))

    def test_another_users_report_is_404_for_every_operation(self):
        edit = reverse("reports:edit_report", args=[self.theirs.pk])
        delete = reverse("reports:delete_report", args=[self.theirs.pk])
        requests = [
            ("get", edit, None),
            ("post", edit, {**self.data, "taxi_fare": "1.00"}),
            ("get", delete, None),
            ("post", delete, None),
        ]
        for method, url, data in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, data)
                self.assertEqual(response.status_code, 404)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.taxi_fare, Decimal("33.00"))

    def test_another_users_report_is_not_listed(self):
        response = self.client.get(reverse("reports:my_reports"))
        self.assertNotContains(response, "$33.00")

    def test_missing_report_is_404(self):
        response = self.client.get(reverse("reports:edit_report", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_guests_are_sent_to_sign_in(self):
        guest = Client()
        signin = reverse("accounts:signin")
        for url in (
            reverse("reports:my_reports"),
            reverse("reports:edit_report", args=[self.theirs.pk]),
            reverse("reports:delete_report", args=[self.theirs.pk]),
        ):
            with self.subTest(url=url):
                response = guest.get(url)
                self.assertRedirects(
                    response, f"{signin}?next={url}", fetch_redirect_response=False
                )

    def test_edit_and_delete_require_csrf(self):
        mine = self.make_report()
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        edit = reverse("reports:edit_report", args=[mine.pk])
        delete = reverse("reports:delete_report", args=[mine.pk])
        self.assertEqual(strict.post(edit, self.data).status_code, 403)
        self.assertEqual(strict.post(delete).status_code, 403)
        self.assertTrue(FareReport.objects.filter(pk=mine.pk).exists())
        self.assertContains(self.client.get(edit), "csrfmiddlewaretoken")
        self.assertContains(self.client.get(delete), "csrfmiddlewaretoken")

    def test_other_methods_are_not_allowed(self):
        mine = self.make_report()
        self.assertEqual(
            self.client.put(reverse("reports:my_reports")).status_code, 405
        )
        self.assertEqual(
            self.client.put(reverse("reports:edit_report", args=[mine.pk])).status_code,
            405,
        )
        self.assertEqual(
            self.client.put(
                reverse("reports:delete_report", args=[mine.pk])
            ).status_code,
            405,
        )
