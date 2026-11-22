"""US47 #121: Restrict an Account."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts import restriction
from accounts.models import AccountAction, Profile
from reports.models import FareReport
from rides.models import RideInterest, RideMessage, RidePost
from rides.tests.test_show_interest import (
    NOW,
    PASSWORD,
    TOMORROW,
    InterestTestData,
    at,
)
from zones.views import NYC_TZ

CHANGELIST = reverse("admin:auth_user_changelist")
TODAY = NOW.date()  # Wednesday 11 Nov 2026 in New York


class RestrictionTestData(InterestTestData):
    """self.rider (Night Owl) is the client's signed-in user; self.owner
    (Early Bird) owns the posts; self.staff is an administrator."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.staff = get_user_model().objects.create_superuser(
            "staff@example.com", password=PASSWORD
        )

    def setUp(self):
        super().setUp()
        self.ride = self.post()
        self.staff_client = Client()
        self.staff_client.force_login(self.staff)

    def restrict(self, user=None, reason="Spam in messages", end=None):
        return restriction.restrict((user or self.rider).pk, self.staff, reason, end)

    def lift(self, user=None, reason="Apologised"):
        return restriction.lift((user or self.rider).pk, self.staff, reason)

    def admin_action(self, action, user=None, **data):
        return self.staff_client.post(
            CHANGELIST,
            {"action": action, "_selected_action": (user or self.rider).pk, **data},
            follow=True,
        )

    def set_now(self, moment):
        patcher = mock.patch("django.utils.timezone.now", return_value=moment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def chat(self, post=None, rider=None):
        post = post or self.ride
        return reverse("rides:conversation", args=[post.pk, (rider or self.rider).pk])

    def send(self, text="Hello"):
        return self.client.post(self.chat(), {"text": text})

    def report_data(self):
        ride = (NOW - timedelta(days=2)).replace(minute=0)
        return {
            "pickup_zone": self.midtown.pk,
            "dropoff_zone": self.jfk.pk,
            "ride_at": ride.astimezone(NYC_TZ).strftime("%Y-%m-%dT%H:%M"),
            "taxi_fare": "21.50",
            "rideshare_service": "",
            "rideshare_quote": "",
        }

    def post_data(self):
        return {
            "pickup_zone": self.midtown.pk,
            "dropoff_zone": self.jfk.pk,
            "departure_at": at(TOMORROW, 18).strftime("%Y-%m-%dT%H:%M"),
            "seats": 2,
            "note": "",
        }


class RestrictedUserIsBlockedTests(RestrictionTestData):
    """A restricted user can browse but cannot post, show interest, message
    or report a fare, and sees why."""

    def setUp(self):
        super().setUp()
        self.restrict(reason="Spam in messages", end=date(2026, 11, 20))
        self.notice = restriction.blocked_notice(self.rider)

    def test_notice_says_why_and_until_when(self):
        self.assertIn("Spam in messages", self.notice)
        self.assertIn("until the end of Fri 20 Nov 2026", self.notice)
        self.assertIn("post rides, show interest, send messages", self.notice)

    def test_notice_without_an_end_date(self):
        self.restrict(reason="Abusive notes")
        notice = restriction.blocked_notice(self.rider)
        self.assertIn("Your account is restricted, so you can't", notice)
        self.assertIn("Abusive notes", notice)

    def test_can_still_sign_in(self):
        self.client.logout()
        response = self.client.post(
            reverse("accounts:signin"),
            {"username": self.rider.username, "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.rider.pk)

    def test_can_still_browse_and_use_saved_items(self):
        for name, args in [
            ("zones:map", []),
            ("zones:compare", []),
            ("rides:find_rides", []),
            ("rides:my_rides", []),
            ("rides:ride_detail", [self.ride.pk]),
            ("routes:my_routes", []),
            ("routes:my_plans", []),
            ("routes:my_comparisons", []),
            ("reports:my_reports", []),
        ]:
            with self.subTest(page=name):
                self.assertEqual(
                    self.client.get(reverse(name, args=args)).status_code, 200
                )

    def test_cannot_post_a_ride(self):
        page = self.client.get(reverse("rides:post_ride"))
        self.assertContains(page, "Spam in messages")
        self.assertContains(page, 'id="account-restricted"')
        self.assertNotContains(page, "Post shared ride</button>")
        response = self.client.post(reverse("rides:post_ride"), self.post_data())
        self.assertContains(response, "Spam in messages")
        self.assertFalse(RidePost.objects.filter(owner=self.rider).exists())

    def test_cannot_edit_own_post(self):
        mine = self.post(owner=self.rider)
        url = reverse("rides:edit_ride", args=[mine.pk])
        response = self.client.post(url, {**self.post_data(), "note": "New text"})
        self.assertRedirects(response, self.detail(mine), fetch_redirect_response=False)
        self.assertEqual(self.messages(response), [self.notice])
        mine.refresh_from_db()
        self.assertEqual(mine.note, "")

    def test_cannot_show_interest(self):
        response = self.show(self.ride)
        self.assertEqual(self.messages(response), [self.notice])
        self.assertFalse(RideInterest.objects.exists())

    def test_interest_button_is_replaced_by_the_notice(self):
        for url in (reverse("rides:find_rides"), self.detail(self.ride)):
            with self.subTest(url=url):
                page = self.client.get(
                    url,
                    {"from": self.midtown.pk, "to": self.jfk.pk},
                )
                self.assertNotContains(page, "I'm interested</button>")
        detail = self.client.get(self.detail(self.ride))
        self.assertContains(detail, "Spam in messages")

    def test_cannot_send_a_message(self):
        self.interest(self.ride)
        RideMessage.objects.create(
            post=self.ride, sender=self.owner, receiver=self.rider, text="Hi?"
        )
        page = self.client.get(self.chat())
        self.assertContains(page, "Hi?")  # can still read
        self.assertContains(page, "Spam in messages")
        self.assertNotContains(page, 'id="conversation-form"')
        response = self.send("Buy my stuff")
        self.assertContains(response, "Spam in messages")
        self.assertFalse(RideMessage.objects.filter(sender=self.rider).exists())

    def test_open_conversation_is_told_by_the_poll(self):
        self.interest(self.ride)
        url = reverse("rides:conversation_updates", args=[self.ride.pk, self.rider.pk])
        data = self.client.get(url).json()
        self.assertIn("Spam in messages", data["read_only"])

    def test_cannot_report_a_fare(self):
        url = reverse("reports:report_fare")
        page = self.client.get(url)
        self.assertContains(page, "Spam in messages")
        self.assertNotContains(page, "Submit fare report</button>")
        response = self.client.post(url, self.report_data())
        self.assertContains(response, "Spam in messages")
        self.assertFalse(FareReport.objects.exists())

    def test_cannot_edit_a_fare_report(self):
        report = FareReport.objects.create(
            user=self.rider,
            pickup_zone=self.midtown,
            dropoff_zone=self.jfk,
            ride_at=NOW - timedelta(days=2),
            taxi_fare=Decimal("20.00"),
        )
        url = reverse("reports:edit_report", args=[report.pk])
        response = self.client.post(url, {**self.report_data(), "taxi_fare": "99"})
        self.assertRedirects(
            response, reverse("reports:my_reports"), fetch_redirect_response=False
        )
        self.assertEqual(self.messages(response), [self.notice])
        report.refresh_from_db()
        self.assertEqual(report.taxi_fare, Decimal("20.00"))

    def test_can_still_manage_own_content(self):
        mine = self.post(owner=self.rider, departure=at(TOMORROW, 11))
        other = self.post(owner=self.rider2, departure=at(TOMORROW, 12))
        asked = self.interest(other)
        pending = self.interest(mine, rider=self.owner)
        accept = reverse("rides:accept_interest", args=[mine.pk, pending.pk])
        self.client.post(accept)
        pending.refresh_from_db()
        self.assertEqual(pending.status, RideInterest.ACCEPTED)
        self.withdraw(other)
        self.assertFalse(RideInterest.objects.filter(pk=asked.pk).exists())
        self.client.post(reverse("rides:close_ride", args=[mine.pk]))
        mine.refresh_from_db()
        self.assertEqual(mine.status, RidePost.CLOSED)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.rider2 = get_user_model().objects.create_user(
            "third@example.com", password=PASSWORD
        )
        Profile.objects.create(user=cls.rider2, display_name="Third Rider")

    def test_other_riders_are_not_affected(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("rides:post_ride")), "<form")
        self.assertIsNone(restriction.blocked_notice(self.owner))

    def test_restricted_owner_still_gets_messages(self):
        mine = self.post(owner=self.rider, departure=at(TOMORROW, 11))
        self.interest(mine, rider=self.owner)
        other = Client()
        other.force_login(self.owner)
        url = reverse("rides:conversation", args=[mine.pk, self.owner.pk])
        other.post(url, {"text": "Still on?"})
        self.assertTrue(RideMessage.objects.filter(sender=self.owner).exists())


class EndDateTests(RestrictionTestData):
    """A restriction with an end date stops applying after that date."""

    def test_applies_through_the_end_date(self):
        self.restrict(end=TODAY)
        self.set_now(datetime(2026, 11, 11, 23, 59, tzinfo=NYC_TZ))
        self.assertIsNotNone(restriction.active_restriction(self.rider))

    def test_stops_applying_the_day_after(self):
        self.restrict(end=TODAY)
        self.set_now(datetime(2026, 11, 12, 0, 0, tzinfo=NYC_TZ))
        self.assertIsNone(restriction.active_restriction(self.rider))
        response = self.client.post(reverse("rides:post_ride"), self.post_data())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(RidePost.objects.filter(owner=self.rider).exists())

    def test_automatic_lift_is_recorded_once(self):
        self.restrict(end=TODAY)
        self.set_now(datetime(2026, 11, 13, 9, 0, tzinfo=NYC_TZ))
        restriction.active_restriction(self.rider)
        restriction.active_restriction(self.rider)
        self.show(self.ride)
        lifts = AccountAction.objects.filter(action=AccountAction.LIFT)
        self.assertEqual(lifts.count(), 1)
        lift = lifts.get()
        self.assertEqual(lift.acted_by, restriction.AUTO_LIFT_BY)
        self.assertEqual(lift.reason, "End date 2026-11-11 passed")
        self.assertEqual(lift.acted_at, datetime(2026, 11, 13, 9, 0, tzinfo=NYC_TZ))

    def test_no_end_date_never_ends(self):
        self.restrict()
        self.set_now(datetime(2030, 1, 1, tzinfo=NYC_TZ))
        self.assertIsNotNone(restriction.active_restriction(self.rider))

    def test_end_date_cannot_be_in_the_past(self):
        changed, message = self.restrict(end=TODAY - timedelta(days=1))
        self.assertFalse(changed)
        self.assertEqual(message, "The end date can't be in the past.")
        self.assertFalse(AccountAction.objects.exists())

    def test_end_date_is_stored_as_the_start_of_the_next_day(self):
        self.restrict(end=date(2026, 11, 20))
        action = AccountAction.objects.get()
        self.assertEqual(action.ends_at, datetime(2026, 11, 21, tzinfo=NYC_TZ))
        self.assertEqual(restriction.last_day(action), date(2026, 11, 20))


class LiftTests(RestrictionTestData):
    """Lifting a restriction restores those features straight away."""

    def test_lifting_restores_everything_at_once(self):
        self.restrict()
        self.assertEqual(self.show(self.ride).status_code, 302)
        self.assertFalse(RideInterest.objects.exists())
        changed, message = self.lift()
        self.assertEqual((changed, message), (True, "Restriction lifted."))
        self.show(self.ride)
        self.assertTrue(RideInterest.objects.filter(rider=self.rider).exists())
        self.assertEqual(self.send("Hello again").status_code, 302)
        self.assertTrue(RideMessage.objects.filter(sender=self.rider).exists())
        page = self.client.get(reverse("reports:report_fare"))
        self.assertNotContains(page, 'id="account-restricted"')
        self.assertContains(page, "Submit fare report</button>")

    def test_cannot_lift_an_account_that_is_not_restricted(self):
        changed, message = self.lift()
        self.assertFalse(changed)
        self.assertIn("is not restricted", message)
        self.assertFalse(AccountAction.objects.exists())

    def test_lifting_an_ended_restriction_records_only_the_automatic_lift(self):
        self.restrict(end=TODAY)
        self.set_now(datetime(2026, 11, 14, tzinfo=NYC_TZ))
        changed, _ = self.lift()
        self.assertFalse(changed)
        self.assertEqual(
            list(
                AccountAction.objects.filter(action=AccountAction.LIFT).values_list(
                    "acted_by", flat=True
                )
            ),
            [restriction.AUTO_LIFT_BY],
        )

    def test_restricting_again_replaces_reason_and_end_date(self):
        self.restrict(reason="First", end=date(2026, 11, 20))
        self.restrict(reason="Second")
        current = restriction.active_restriction(self.rider)
        self.assertEqual((current.reason, current.ends_at), ("Second", None))

    def test_restriction_after_a_lift_applies_again(self):
        self.restrict()
        self.lift()
        self.restrict(reason="Again")
        self.assertEqual(restriction.active_restriction(self.rider).reason, "Again")


class RecordTests(RestrictionTestData):
    """Every restriction and lift records the admin, the time and the reason."""

    def test_restrict_and_lift_are_recorded(self):
        self.restrict(reason="  Spam  ", end=date(2026, 11, 20))
        self.set_now(NOW + timedelta(hours=2))
        self.lift(reason="Resolved")
        restrict_row, lift_row = AccountAction.objects.order_by("acted_at")
        self.assertEqual(
            (restrict_row.action, restrict_row.acted_by, restrict_row.reason),
            (AccountAction.RESTRICT, "staff@example.com", "Spam"),
        )
        self.assertEqual(restrict_row.acted_at, NOW)
        self.assertEqual(
            (lift_row.action, lift_row.acted_by, lift_row.reason, lift_row.ends_at),
            (AccountAction.LIFT, "staff@example.com", "Resolved", None),
        )
        self.assertEqual(lift_row.acted_at, NOW + timedelta(hours=2))

    def test_reason_is_required(self):
        for call in (lambda: self.restrict(reason="  "), lambda: self.lift(reason="")):
            changed, message = call()
            self.assertFalse(changed)
            self.assertIn("Enter a reason", message)
        self.assertFalse(AccountAction.objects.exists())

    def test_cannot_restrict_own_account(self):
        changed, message = restriction.restrict(self.staff.pk, self.staff, "Test")
        self.assertFalse(changed)
        self.assertEqual(message, "You cannot restrict your own account.")


class AdminActionTests(RestrictionTestData):
    def test_restrict_action_with_reason_and_end_date(self):
        response = self.admin_action(
            "restrict_accounts", reason="Spam", restriction_end="2026-11-20"
        )
        self.assertContains(response, "1 account(s) restricted.")
        action = AccountAction.objects.get()
        self.assertEqual(
            (action.action, action.reason, action.acted_by),
            (AccountAction.RESTRICT, "Spam", "staff@example.com"),
        )
        self.assertEqual(restriction.last_day(action), date(2026, 11, 20))

    def test_restrict_action_without_an_end_date(self):
        self.admin_action("restrict_accounts", reason="Spam", restriction_end="")
        self.assertIsNone(AccountAction.objects.get().ends_at)

    def test_restrict_action_needs_a_reason(self):
        response = self.admin_action("restrict_accounts", reason=" ")
        self.assertContains(response, "Enter a reason before restricting or lifting.")
        self.assertFalse(AccountAction.objects.exists())

    def test_restrict_action_refuses_a_bad_or_past_date(self):
        response = self.admin_action(
            "restrict_accounts", reason="Spam", restriction_end="20/11/2026"
        )
        self.assertContains(response, "Enter the end date as YYYY-MM-DD.")
        response = self.admin_action(
            "restrict_accounts", reason="Spam", restriction_end="2026-11-01"
        )
        self.assertContains(response, "The end date can&#x27;t be in the past.")
        self.assertFalse(AccountAction.objects.exists())

    def test_lift_action(self):
        self.restrict()
        response = self.admin_action("lift_restrictions", reason="Resolved")
        self.assertContains(response, "1 account(s) lifted.")
        self.assertIsNone(restriction.active_restriction(self.rider))
        response = self.admin_action("lift_restrictions", reason="Again")
        self.assertContains(response, "is not restricted")

    def test_list_shows_who_is_restricted(self):
        self.restrict(end=date(2026, 11, 20))
        self.restrict(user=self.owner)
        page = self.staff_client.get(CHANGELIST)
        self.assertContains(page, "Until 2026-11-20")
        self.assertContains(page, "Yes, no end date")

    def test_list_shows_ended_and_lifted_restrictions_as_not_restricted(self):
        self.restrict(end=TODAY)
        self.restrict(user=self.owner)
        restriction.lift(self.owner.pk, self.staff, "Done")
        self.set_now(datetime(2026, 11, 12, 9, 0, tzinfo=NYC_TZ))
        page = self.staff_client.get(CHANGELIST)
        self.assertNotContains(page, "Until 2026-11-11")
        self.assertNotContains(page, "Yes, no end date")

    def test_account_page_shows_the_history(self):
        self.restrict(reason="Spam", end=date(2026, 11, 20))
        self.lift(reason="Resolved")
        self.restrict(reason="Again")
        page = self.staff_client.get(
            reverse("admin:auth_user_change", args=[self.rider.pk])
        )
        self.assertContains(page, "Restrict until 2026-11-20: Spam (staff@example.com")
        self.assertContains(page, "Lift restriction: Resolved (staff@example.com")
        self.assertContains(page, "Restrict (no end date): Again")

    def test_riders_cannot_use_the_actions(self):
        response = self.client.post(
            CHANGELIST,
            {
                "action": "restrict_accounts",
                "_selected_action": self.owner.pk,
                "reason": "x",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AccountAction.objects.exists())


class QueryCostTests(RestrictionTestData):
    def test_pages_without_blocked_features_do_not_check(self):
        self.restrict()
        with mock.patch.object(restriction, "active_restriction") as check:
            self.client.get(reverse("routes:my_routes"))
            self.client.get(reverse("rides:my_rides"))
        check.assert_not_called()


class EdgeCaseTests(RestrictionTestData):
    def test_guests_are_never_restricted(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertIsNone(restriction.active_restriction(AnonymousUser()))
        self.assertIsNone(restriction.active_restriction(None))

    def test_automatic_lift_skips_a_restriction_already_replaced(self):
        # Two requests see the same ended restriction; the first one's lift
        # (or an admin's new restriction) wins, and the second records nothing.
        self.restrict(end=TODAY)
        old = AccountAction.objects.get()
        self.restrict(reason="Newer")
        restriction._lift_expired(self.rider.pk, old)
        self.assertFalse(
            AccountAction.objects.filter(action=AccountAction.LIFT).exists()
        )

    def test_lift_rechecks_under_the_lock(self):
        # Another admin lifted it between the check and the lock.
        self.restrict()
        self.lift()
        with mock.patch.object(
            restriction, "active_restriction", return_value=object()
        ):
            changed, message = self.lift()
        self.assertFalse(changed)
        self.assertIn("is not restricted", message)
        self.assertEqual(
            AccountAction.objects.filter(action=AccountAction.LIFT).count(), 1
        )
