"""US44 #118: Review Fare Reports Held for Review. Held reports are listed
first in the admin with the route's historical average to compare against;
approving a report makes it count in the rider reports summary (US26);
removing one hides it from every public view and its owner sees that it was
removed; every approval and removal records the admin and the time.
(Guests and riders are refused on every admin URL by
accounts/tests/test_admin_access.py.)"""

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.html import escape

from reports import review
from reports.models import FareReport
from reports.tests.test_fare_reports import FareReportTestData
from reports.views import REMOVED_NOT_EDITABLE

NOW = datetime(2026, 11, 18, 15, 30, tzinfo=dt_timezone.utc)
CHANGELIST = reverse("admin:reports_farereport_changelist")
VISIBLE, HELD, REMOVED = FareReport.VISIBLE, FareReport.HELD, FareReport.REMOVED


class ReviewData(FareReportTestData):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.staff = get_user_model().objects.create_superuser(
            "staff@example.com", "staff@example.com", "taxi-route-7319"
        )

    def summary(self):
        return self.client.get(
            reverse("reports:route_reports"), {"from": 161, "to": 237}
        ).json()


class ReviewRulesTests(ReviewData):
    def test_approve_makes_held_reports_visible_with_who_and_when(self):
        report = self.make_report(status=HELD)

        changed = review.approve(
            FareReport.objects.all(), "staff@example.com", "  Real fare  ", now=NOW
        )

        report.refresh_from_db()
        self.assertEqual(changed, 1)
        self.assertEqual(report.status, VISIBLE)
        self.assertEqual(
            (report.reviewed_by, report.reviewed_at, report.review_reason),
            ("staff@example.com", NOW, "Real fare"),
        )

    def test_remove_hides_a_report_with_who_and_when(self):
        report = self.make_report(status=HELD)

        review.remove(FareReport.objects.all(), "staff@example.com", now=NOW)

        report.refresh_from_db()
        self.assertEqual(report.status, REMOVED)
        self.assertEqual(
            (report.reviewed_by, report.reviewed_at), ("staff@example.com", NOW)
        )
        self.assertEqual(report.review_reason, "")

    def test_reports_already_at_that_status_are_left_alone(self):
        visible = self.make_report()

        changed = review.approve(FareReport.objects.all(), "staff@example.com")

        visible.refresh_from_db()
        self.assertEqual(changed, 0)
        self.assertEqual(visible.reviewed_by, "")
        self.assertIsNone(visible.reviewed_at)

    def test_without_now_the_current_time_is_recorded(self):
        report = self.make_report(status=HELD)

        with mock.patch("reports.review.timezone.now", return_value=NOW):
            review.remove(FareReport.objects.all(), "staff@example.com")

        report.refresh_from_db()
        self.assertEqual(report.reviewed_at, NOW)

    def test_removed_reports_are_never_public(self):
        self.make_report(status=REMOVED)

        self.assertFalse(FareReport.objects.public().exists())

    def test_usual_fare_is_the_route_average_at_that_day_and_hour(self):
        report = self.make_report(status=HELD)

        stats = review.usual_fare(report)

        self.assertTrue(stats["enough_data"])
        self.assertEqual(stats["fare_avg"], Decimal("20.00"))


class SummaryTests(ReviewData):
    """US26: approving counts the report; removing takes it out."""

    def test_approving_a_held_report_counts_it_in_the_summary(self):
        self.make_report(taxi_fare=Decimal("19.00"))
        self.make_report(taxi_fare=Decimal("21.00"))
        held = self.make_report(taxi_fare=Decimal("70.00"), status=HELD)
        self.assertFalse(self.summary()["enough_data"])

        review.approve(FareReport.objects.filter(pk=held.pk), "staff@example.com")

        summary = self.summary()
        self.assertEqual(summary["report_count"], 3)
        self.assertEqual(summary["median_taxi_fare"], "21.00")

    def test_removing_a_visible_report_takes_it_out_of_the_summary(self):
        for fare in ("19.00", "20.00", "21.00"):
            self.make_report(taxi_fare=Decimal(fare))
        self.assertEqual(self.summary()["report_count"], 3)

        review.remove(
            FareReport.objects.filter(taxi_fare=Decimal("20.00")), "staff@example.com"
        )

        summary = self.summary()
        self.assertEqual(summary["report_count"], 2)
        self.assertFalse(summary["enough_data"])


class ReviewAdminTests(ReviewData):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)

    def act(self, action, reports, reason=""):
        return self.client.post(
            CHANGELIST,
            {
                "action": action,
                "_selected_action": [report.pk for report in reports],
                "reason": reason,
            },
            follow=True,
        )

    def test_held_reports_are_listed_first(self):
        held = self.make_report(status=HELD)
        newer = self.make_report()

        response = self.client.get(CHANGELIST)

        self.assertEqual(list(response.context["cl"].result_list), [held, newer])

    def test_each_report_shows_the_usual_fare_to_compare_against(self):
        self.make_report(status=HELD, taxi_fare=Decimal("90.00"))
        self.make_report(
            pickup_zone=self.jfk, dropoff_zone=self.ues, taxi_fare=Decimal("50.00")
        )

        response = self.client.get(CHANGELIST)

        self.assertContains(response, "$20.00 (50 trips)")
        self.assertContains(response, "Not enough data")
        self.assertContains(response, "Midtown Center → Upper East Side South")

    def test_approve_with_a_reason(self):
        report = self.make_report(status=HELD)

        response = self.act("approve_reports", [report], reason="Checked receipt")

        report.refresh_from_db()
        self.assertContains(response, "1 report approved.")
        self.assertEqual(report.status, VISIBLE)
        self.assertEqual(report.reviewed_by, "staff@example.com")
        self.assertIsNotNone(report.reviewed_at)
        self.assertEqual(report.review_reason, "Checked receipt")

    def test_remove_several_and_say_which_were_already_removed(self):
        held = self.make_report(status=HELD)
        done = self.make_report(status=REMOVED)
        visible = self.make_report()

        response = self.act("remove_reports", [held, done, visible])

        self.assertContains(
            response, "2 reports removed. 1 already removed, left as they were."
        )
        self.assertEqual(FareReport.objects.filter(status=REMOVED).count(), 3)

    def test_the_reason_box_is_next_to_the_actions(self):
        self.make_report(status=HELD)

        response = self.client.get(CHANGELIST)

        self.assertContains(response, "Reason (optional)")
        self.assertContains(response, "Approve: show to other riders")
        self.assertContains(response, "Remove: hide from every public view")

    def test_status_cannot_be_changed_on_the_report_page(self):
        report = self.make_report(status=HELD)
        url = reverse("admin:reports_farereport_change", args=[report.pk])

        page = self.client.get(url)
        self.client.post(url, {"status": VISIBLE})

        report.refresh_from_db()
        self.assertEqual(report.status, HELD)
        self.assertNotContains(page, 'name="status"')
        self.assertContains(page, "$20.00 (50 trips)")

    def test_reports_cannot_be_added_in_the_admin(self):
        response = self.client.get(reverse("admin:reports_farereport_add"))

        self.assertEqual(response.status_code, 403)


class OwnerSeesRemovalTests(ReviewData):
    def test_my_reports_says_removed_by_a_moderator_without_an_edit_link(self):
        report = self.make_report(status=REMOVED)

        response = self.client.get(reverse("reports:my_reports"))

        self.assertContains(
            response, 'class="report-status-removed">Removed by a moderator<'
        )
        self.assertNotContains(
            response, reverse("reports:edit_report", args=[report.pk])
        )
        self.assertContains(
            response, reverse("reports:delete_report", args=[report.pk])
        )

    def test_a_removed_report_cannot_be_edited_back(self):
        report = self.make_report(status=REMOVED)
        url = reverse("reports:edit_report", args=[report.pk])

        page = self.client.get(url, follow=True)
        self.client.post(url, {**self.data, "taxi_fare": "25.00"})

        report.refresh_from_db()
        self.assertEqual(report.status, REMOVED)
        self.assertEqual(report.taxi_fare, Decimal("20.00"))
        self.assertRedirects(page, reverse("reports:my_reports"))
        self.assertContains(page, escape(REMOVED_NOT_EDITABLE))

    def test_a_removed_report_can_still_be_deleted(self):
        report = self.make_report(status=REMOVED)

        self.client.post(reverse("reports:delete_report", args=[report.pk]))

        self.assertFalse(FareReport.objects.filter(pk=report.pk).exists())
