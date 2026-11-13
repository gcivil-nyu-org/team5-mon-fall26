"""US33 #95: Show Interest in a Shared Ride."""

from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.http import urlencode

from accounts.models import Profile
from rides import interest as ride_interest
from rides.models import RideInterest, RidePost
from zones.models import Zone
from zones.views import NYC_TZ

PASSWORD = "a-strong-test-password-33"
# Wednesday 11 Nov 2026, 08:00 in New York. Every test runs at this moment.
NOW = datetime(2026, 11, 11, 8, 0, tzinfo=NYC_TZ)
TOMORROW = NOW.date() + timedelta(days=1)


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), NYC_TZ)


class InterestTestData(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.rider = users.create_user("alex.k@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.rider, display_name="Night Owl")
        cls.owner = users.create_user("sam.owner@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.owner, display_name="Early Bird")
        cls.midtown = Zone.objects.create(
            zone_id=161, name="Midtown Center", borough="Manhattan"
        )
        cls.jfk = Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.rider)

    def post(self, owner=None, departure=None, **fields):
        return RidePost.objects.create(
            owner=owner or self.owner,
            pickup_zone=self.midtown,
            dropoff_zone=self.jfk,
            departure_at=departure or at(TOMORROW, 9),
            seats=fields.pop("seats", 2),
            **fields,
        )

    def interest(self, post, rider=None, **fields):
        return RideInterest.objects.create(
            post=post, rider=rider or self.rider, **fields
        )

    def detail(self, post):
        return reverse("rides:ride_detail", args=[post.pk])

    def show(self, post, **data):
        return self.client.post(reverse("rides:show_interest", args=[post.pk]), data)

    def withdraw(self, post, **data):
        return self.client.post(
            reverse("rides:withdraw_interest", args=[post.pk]), data
        )

    def messages(self, response):
        """The message this request added (messages from earlier requests in
        the same test are still waiting in the session, unread)."""
        return [str(m) for m in response.wsgi_request._messages][-1:]


class ModelTests(InterestTestData):
    def test_new_interest_is_pending_with_a_created_date(self):
        interest = self.interest(self.post())
        self.assertEqual(interest.status, RideInterest.PENDING)
        self.assertEqual(interest.get_status_display(), "Pending")
        self.assertEqual(interest.created_at, NOW)
        self.assertEqual(str(interest), "Night Owl: Pending")

    def test_one_interest_per_rider_per_post(self):
        post = self.post()
        self.interest(post)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.interest(post)

    def test_database_refuses_an_unknown_status(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.interest(self.post(), status="maybe")

    def test_deleting_the_riders_account_deletes_the_interest(self):
        interest = self.interest(self.post())
        self.rider.delete()
        self.assertFalse(RideInterest.objects.filter(pk=interest.pk).exists())

    def test_deleting_the_owners_account_deletes_the_interest(self):
        interest = self.interest(self.post())
        self.owner.delete()
        self.assertFalse(RideInterest.objects.filter(pk=interest.pk).exists())

    def test_interest_is_in_the_admin(self):
        self.assertIn(RideInterest, admin.site._registry)

    def test_str_without_a_display_name(self):
        nameless = get_user_model().objects.create_user(
            "no.name@example.com", password=PASSWORD
        )
        interest = self.interest(self.post(), rider=nameless)
        self.assertEqual(str(interest), f"rider {nameless.pk}: Pending")


class ShowInterestTests(InterestTestData):
    def test_a_rider_shows_interest_in_an_open_post_once(self):
        post = self.post()
        response = self.show(post)
        self.assertRedirects(response, self.detail(post))
        self.assertEqual(
            self.messages(response),
            [ride_interest.SHOWN],
        )
        interest = RideInterest.objects.get(post=post, rider=self.rider)
        self.assertEqual(interest.status, RideInterest.PENDING)

        response = self.show(post)
        self.assertEqual(self.messages(response), [ride_interest.ALREADY])
        self.assertEqual(RideInterest.objects.filter(post=post).count(), 1)

    def test_the_owner_and_status_never_come_from_the_request(self):
        post = self.post()
        self.show(post, rider=self.owner.pk, status="accepted")
        interest = RideInterest.objects.get(post=post)
        self.assertEqual(interest.rider, self.rider)
        self.assertEqual(interest.status, RideInterest.PENDING)

    def test_blocked_posts(self):
        cases = [
            (self.post(owner=self.rider), ride_interest.OWN_POST),
            (self.post(status=RidePost.FULL), ride_interest.FULL),
            (self.post(status=RidePost.CLOSED), ride_interest.CLOSED),
            (self.post(departure=at(NOW.date(), 7, 45)), ride_interest.EXPIRED),
        ]
        for post, message in cases:
            with self.subTest(message=message):
                response = self.show(post)
                self.assertRedirects(
                    response,
                    reverse("rides:find_rides"),
                    fetch_redirect_response=False,
                )
                self.assertEqual(self.messages(response), [message])
                self.assertFalse(RideInterest.objects.filter(post=post).exists())

    def test_a_post_that_departs_exactly_now_is_expired(self):
        post = self.post(departure=NOW)
        self.assertEqual(self.messages(self.show(post)), [ride_interest.EXPIRED])

    def test_an_interest_saved_meanwhile_counts_as_already_shown(self):
        post = self.post()
        real_exists = ride_interest.RideInterest.objects.filter

        def saved_meanwhile(*args, **kwargs):
            # The check sees nothing; another request saves the row first.
            self.interest(post)
            return RideInterest.objects.none()

        with mock.patch.object(ride_interest, "_existing", side_effect=saved_meanwhile):
            response = self.show(post)
        self.assertEqual(self.messages(response), [ride_interest.ALREADY])
        self.assertEqual(real_exists(post=post).count(), 1)

    def test_it_goes_back_to_the_page_it_came_from(self):
        post = self.post()
        search = reverse("rides:find_rides") + "?from=161&to=132&date=2026-11-12"
        response = self.show(post, next=search)
        self.assertRedirects(response, search, fetch_redirect_response=False)

    def test_another_site_in_next_is_ignored(self):
        post = self.post()
        response = self.show(post, next="https://evil.example.com/")
        self.assertRedirects(response, self.detail(post))

    def test_an_unknown_post_is_404(self):
        response = self.client.post(reverse("rides:show_interest", args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_only_post_is_allowed(self):
        post = self.post()
        url = reverse("rides:show_interest", args=[post.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_guests_are_sent_to_sign_in_and_nothing_is_saved(self):
        post = self.post()
        response = Client().post(reverse("rides:show_interest", args=[post.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("accounts:signin")))
        self.assertFalse(RideInterest.objects.exists())

    def test_a_rider_without_a_display_name_chooses_one_first(self):
        nameless = get_user_model().objects.create_user(
            "no.name@example.com", password=PASSWORD
        )
        self.client.force_login(nameless)
        post = self.post()
        response = self.show(post)
        self.assertTrue(
            response["Location"].startswith(reverse("accounts:display_name"))
        )
        self.assertFalse(RideInterest.objects.exists())

    def test_a_csrf_token_is_required(self):
        post = self.post()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.rider)
        response = client.post(reverse("rides:show_interest", args=[post.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RideInterest.objects.exists())


class WithdrawTests(InterestTestData):
    def test_a_rider_can_withdraw_and_show_interest_again(self):
        post = self.post()
        self.interest(post)
        response = self.withdraw(post)
        self.assertRedirects(response, self.detail(post))
        self.assertEqual(self.messages(response), [ride_interest.WITHDRAWN])
        self.assertFalse(RideInterest.objects.exists())

        self.show(post)
        self.assertTrue(RideInterest.objects.filter(post=post).exists())

    def test_an_accepted_rider_can_withdraw(self):
        post = self.post()
        self.interest(post, status=RideInterest.ACCEPTED)
        self.assertEqual(self.messages(self.withdraw(post)), [ride_interest.WITHDRAWN])
        self.assertFalse(RideInterest.objects.exists())

    def test_a_declined_rider_cannot_withdraw_to_ask_again(self):
        post = self.post()
        self.interest(post, status=RideInterest.DECLINED)
        response = self.withdraw(post)
        self.assertEqual(self.messages(response), [ride_interest.DECLINED_STAYS])
        self.assertTrue(RideInterest.objects.exists())
        self.assertEqual(self.messages(self.show(post)), [ride_interest.ALREADY])

    def test_withdrawing_without_interest_says_so(self):
        post = self.post()
        response = self.withdraw(post)
        self.assertEqual(self.messages(response), [ride_interest.NOTHING_TO_WITHDRAW])

    def test_withdrawing_only_removes_the_riders_own_interest(self):
        post = self.post()
        other = get_user_model().objects.create_user(
            "casey@example.com", password=PASSWORD
        )
        theirs = self.interest(post, rider=other)
        self.withdraw(post)
        self.assertTrue(RideInterest.objects.filter(pk=theirs.pk).exists())

    def test_it_goes_back_to_the_page_it_came_from(self):
        post = self.post()
        self.interest(post)
        search = reverse("rides:find_rides") + "?from=161&to=132&date=2026-11-12"
        response = self.withdraw(post, next=search)
        self.assertRedirects(response, search, fetch_redirect_response=False)

    def test_only_post_is_allowed(self):
        post = self.post()
        url = reverse("rides:withdraw_interest", args=[post.pk])
        self.assertEqual(self.client.get(url).status_code, 405)


class PostPageTests(InterestTestData):
    def test_another_rider_sees_an_open_post_with_im_interested(self):
        post = self.post(note="One bag")
        response = self.client.get(self.detail(post))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Early Bird")
        self.assertContains(response, "One bag")
        self.assertContains(response, "2 seats left")
        self.assertContains(response, "I'm interested")
        self.assertContains(
            response, f'action="{reverse("rides:show_interest", args=[post.pk])}"'
        )
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertNotContains(response, "@")
        self.assertNotContains(response, "Withdraw")

    def test_the_rider_sees_their_status_and_withdraw(self):
        for status, label in (
            (RideInterest.PENDING, "Pending"),
            (RideInterest.ACCEPTED, "Accepted"),
        ):
            with self.subTest(status=status):
                post = self.post()
                self.interest(post, status=status)
                response = self.client.get(self.detail(post))
                self.assertContains(
                    response,
                    f'Your interest: <span class="status interest-{status}">'
                    f"{label}</span>",
                )
                self.assertContains(response, "Withdraw")
                self.assertNotContains(response, "I'm interested")

    def test_a_declined_rider_sees_declined_and_no_buttons(self):
        post = self.post()
        self.interest(post, status=RideInterest.DECLINED)
        response = self.client.get(self.detail(post))
        self.assertContains(
            response,
            'Your interest: <span class="status interest-declined">Declined</span>',
        )
        self.assertNotContains(response, "Withdraw")
        self.assertNotContains(response, "I'm interested")

    def test_a_rider_with_interest_still_sees_a_full_closed_or_expired_post(self):
        for fields in (
            {"status": RidePost.FULL},
            {"status": RidePost.CLOSED},
            {"departure": at(NOW.date(), 7)},
        ):
            with self.subTest(fields=fields):
                post = self.post(**fields)
                self.interest(post)
                response = self.client.get(self.detail(post))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Pending")
                self.assertNotContains(response, "I'm interested")

    def test_full_closed_or_expired_posts_are_404_without_interest(self):
        for fields in (
            {"status": RidePost.FULL},
            {"status": RidePost.CLOSED},
            {"departure": at(NOW.date(), 7)},
        ):
            with self.subTest(fields=fields):
                post = self.post(**fields)
                self.assertEqual(self.client.get(self.detail(post)).status_code, 404)

    def test_the_owner_sees_no_interest_buttons_on_their_own_post(self):
        post = self.post(owner=self.rider)
        response = self.client.get(self.detail(post))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "I'm interested")
        self.assertNotContains(response, "Your interest")
        self.assertContains(response, "This is what riders going your way see.")

    def test_a_rider_without_a_display_name_chooses_one_first(self):
        nameless = get_user_model().objects.create_user(
            "no.name@example.com", password=PASSWORD
        )
        self.client.force_login(nameless)
        response = self.client.get(self.detail(self.post()))
        self.assertTrue(
            response["Location"].startswith(reverse("accounts:display_name"))
        )


class SearchResultTests(InterestTestData):
    def search(self):
        params = {"from": 161, "to": 132, "date": TOMORROW.isoformat()}
        return f"{reverse('rides:find_rides')}?{urlencode(params)}"

    def test_each_result_has_im_interested_and_a_link_to_the_post(self):
        post = self.post()
        response = self.client.get(self.search())
        self.assertContains(
            response, f'action="{reverse("rides:show_interest", args=[post.pk])}"'
        )
        self.assertContains(
            response,
            f'<input type="hidden" name="next" value="{self.search()}"'.replace(
                "&", "&amp;"
            ),
        )
        self.assertContains(response, f'href="{self.detail(post)}"')
        self.assertContains(response, "I'm interested")

    def test_a_result_shows_the_riders_status_and_withdraw(self):
        post = self.post()
        self.interest(post)
        response = self.client.get(self.search())
        self.assertContains(
            response,
            'Your interest: <span class="status interest-pending">Pending</span>',
        )
        self.assertContains(
            response, f'action="{reverse("rides:withdraw_interest", args=[post.pk])}"'
        )
        self.assertNotContains(response, "I'm interested")

    def test_the_search_marks_only_the_riders_own_interest(self):
        post = self.post()
        other = get_user_model().objects.create_user(
            "casey@example.com", password=PASSWORD
        )
        self.interest(post, rider=other)
        response = self.client.get(self.search())
        self.assertContains(response, "I'm interested")
        self.assertNotContains(response, "Your interest")
