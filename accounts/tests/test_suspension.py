"""US46: suspension changes access and hides active rider content."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.forms import SIGN_IN_ERROR, SUSPENDED_ERROR
from accounts.models import AccountAction
from accounts.suspension import change_account
from reports import review
from reports.forms import FareReportForm
from reports.models import FareReport
from rides.models import RidePost
from zones.models import Zone


PASSWORD = "a-strong-test-password-46"


class SuspensionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.staff = users.create_superuser("staff@example.com", password=PASSWORD)
        cls.rider = users.create_user("rider@example.com", password=PASSWORD)
        cls.pickup = Zone.objects.create(
            zone_id=161, name="Midtown", borough="Manhattan"
        )
        cls.dropoff = Zone.objects.create(
            zone_id=237, name="Upper East Side", borough="Manhattan"
        )

    def setUp(self):
        self.post = RidePost.objects.create(
            owner=self.rider,
            pickup_zone=self.pickup,
            dropoff_zone=self.dropoff,
            departure_at=timezone.now() + timedelta(days=1),
            seats=2,
        )
        self.report = FareReport.objects.create(
            user=self.rider,
            pickup_zone=self.pickup,
            dropoff_zone=self.dropoff,
            ride_at=timezone.now() - timedelta(days=1),
            taxi_fare=Decimal("20.00"),
        )

    def test_suspend_hides_content_and_password_controls_message(self):
        changed, _ = change_account(
            self.rider.pk, self.staff, AccountAction.SUSPEND, "  Unsafe conduct  "
        )
        self.assertTrue(changed)
        self.rider.refresh_from_db()
        self.post.refresh_from_db()
        self.report.refresh_from_db()
        self.assertFalse(self.rider.is_active)
        self.assertEqual(self.post.status, RidePost.CLOSED)
        self.assertEqual(self.report.status, FareReport.HELD)
        action = AccountAction.objects.get()
        self.assertEqual(
            (action.acted_by, action.reason), ("staff@example.com", "Unsafe conduct")
        )
        self.assertIsNotNone(action.acted_at)
        self.assertEqual(str(action), f"Suspend {self.rider.pk} by staff@example.com")

        url = reverse("accounts:signin")
        wrong = self.client.post(
            url, {"username": self.rider.username, "password": "wrong"}
        )
        self.assertContains(wrong, SIGN_IN_ERROR)
        self.assertNotContains(wrong, SUSPENDED_ERROR)
        right = self.client.post(
            url, {"username": self.rider.username, "password": PASSWORD}
        )
        self.assertContains(right, SUSPENDED_ERROR)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_restore_allows_sign_in_without_reopening_content(self):
        change_account(
            self.rider.pk, self.staff, AccountAction.SUSPEND, "Unsafe conduct"
        )
        changed, _ = change_account(
            self.rider.pk, self.staff, AccountAction.RESTORE, "Appeal accepted"
        )
        self.assertTrue(changed)
        self.assertEqual(AccountAction.objects.count(), 2)
        self.post.refresh_from_db()
        self.report.refresh_from_db()
        self.assertEqual(self.post.status, RidePost.CLOSED)
        self.assertEqual(self.report.status, FareReport.HELD)
        response = self.client.post(
            reverse("accounts:signin"),
            {"username": self.rider.username, "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.rider.pk)

    def test_admin_requires_reason_and_cannot_suspend_self(self):
        self.client.force_login(self.staff)
        url = reverse("admin:auth_user_changelist")
        self.client.post(
            url, {"action": "suspend_accounts", "_selected_action": self.rider.pk}
        )
        self.rider.refresh_from_db()
        self.assertTrue(self.rider.is_active)
        self.client.post(
            url,
            {
                "action": "suspend_accounts",
                "_selected_action": self.staff.pk,
                "reason": "x",
            },
        )
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)
        self.assertFalse(AccountAction.objects.exists())

    def test_last_active_staff_cannot_be_suspended(self):
        actor = get_user_model().objects.create_user(
            "former@example.com", password=PASSWORD
        )
        changed, detail = change_account(
            self.staff.pk, actor, AccountAction.SUSPEND, "x"
        )
        self.assertFalse(changed)
        self.assertIn("last active staff", detail)

    def test_repeated_and_invalid_actions_do_not_create_history(self):
        changed, detail = change_account(
            self.rider.pk, self.staff, AccountAction.RESTORE, "Already active"
        )
        self.assertFalse(changed)
        self.assertEqual(detail, "This account is already active.")
        changed, detail = change_account(
            self.rider.pk, self.staff, AccountAction.SUSPEND, "  "
        )
        self.assertFalse(changed)
        self.assertEqual(detail, "Enter a reason before changing an account.")
        with self.assertRaisesMessage(ValueError, "Unknown account action"):
            change_account(self.rider.pk, self.staff, "invalid", "Reason")
        self.assertFalse(AccountAction.objects.exists())

        changed, _ = change_account(
            self.rider.pk, self.staff, AccountAction.SUSPEND, "Unsafe conduct"
        )
        self.assertTrue(changed)
        changed, detail = change_account(
            self.rider.pk, self.staff, AccountAction.SUSPEND, "Again"
        )
        self.assertFalse(changed)
        self.assertEqual(detail, "This account is already suspended.")
        changed, _ = change_account(
            self.rider.pk, self.staff, AccountAction.RESTORE, "Appeal accepted"
        )
        self.assertTrue(changed)
        changed, detail = change_account(
            self.rider.pk, self.staff, AccountAction.RESTORE, "Again"
        )
        self.assertFalse(changed)
        self.assertEqual(detail, "This account is already active.")
        self.assertEqual(AccountAction.objects.count(), 2)

    def test_admin_restores_selected_account(self):
        change_account(
            self.rider.pk, self.staff, AccountAction.SUSPEND, "Unsafe conduct"
        )
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("admin:auth_user_changelist"),
            {
                "action": "restore_accounts",
                "_selected_action": self.rider.pk,
                "reason": "Appeal accepted",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.rider.refresh_from_db()
        self.assertTrue(self.rider.is_active)
        restored = AccountAction.objects.first()
        self.assertEqual(restored.action, AccountAction.RESTORE)
        self.assertEqual(restored.reason, "Appeal accepted")

    def edit_form(self):
        from zones.views import NYC_TZ

        data = {
            "pickup_zone": self.pickup.pk,
            "dropoff_zone": self.dropoff.pk,
            "ride_at": self.report.ride_at.astimezone(NYC_TZ).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "taxi_fare": "25.00",
            "rideshare_service": "",
            "rideshare_quote": "",
        }
        form = FareReportForm(self.rider, data, instance=self.report)
        self.assertTrue(form.is_valid(), form.errors)
        return form

    def test_in_flight_edit_cannot_republish_after_suspension(self):
        form = self.edit_form()
        change_account(
            self.rider.pk, self.staff, AccountAction.SUSPEND, "Unsafe conduct"
        )
        self.assertIsNone(form.save())
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, FareReport.HELD)

    def test_in_flight_edit_cannot_undo_moderator_removal(self):
        form = self.edit_form()
        review.remove(FareReport.objects.filter(pk=self.report.pk), self.staff.username)
        self.assertIsNone(form.save())
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, FareReport.REMOVED)
