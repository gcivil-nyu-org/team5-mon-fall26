"""US34 #96: Accept or Decline Interested Riders."""

import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse

from accounts.models import Profile
from rides import interest as ride_interest
from rides.models import RideInterest, RidePost
from rides.search import find_rides

from .test_show_interest import PASSWORD, TOMORROW, InterestTestData, at


class AcceptDeclineTests(InterestTestData):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        users = get_user_model().objects
        cls.rider2 = users.create_user("r2@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.rider2, display_name="Second Rider")
        cls.rider3 = users.create_user("r3@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.rider3, display_name="Third Rider")

    def act(self, post, ri, action):
        name = {
            "accept": "accept_interest",
            "decline": "decline_interest",
            "undo": "undo_acceptance",
        }[action]
        return self.client.post(reverse(f"rides:{name}", args=[post.pk, ri.pk]))

    def as_owner(self):
        self.client.force_login(self.owner)

    # Owner sees every interested rider by display name, never email
    def test_owner_sees_all_interested_riders(self):
        post = self.post(seats=2)
        self.interest(post)
        self.interest(post, rider=self.rider2, status=RideInterest.DECLINED)
        self.as_owner()
        r = self.client.get(self.detail(post))
        self.assertContains(r, "Night Owl")
        self.assertContains(r, "Second Rider")
        self.assertNotContains(r, "@example.com")

    # Accepting the last seat -> Full and hidden from search
    def test_accept_last_seat_marks_full_and_hides_from_search(self):
        post = self.post(seats=1)
        ri = self.interest(post)
        self.as_owner()
        self.act(post, ri, "accept")
        post.refresh_from_db()
        ri.refresh_from_db()
        self.assertEqual(ri.status, RideInterest.ACCEPTED)
        self.assertEqual(post.status, RidePost.FULL)
        results = find_rides(self.rider3, self.midtown, self.jfk, TOMORROW)
        self.assertNotIn(post.pk, [m.post.pk for m in results])

    # Undo frees the seat and reopens
    def test_undo_reopens_full_post(self):
        post = self.post(seats=1)
        ri = self.interest(post, status=RideInterest.ACCEPTED)
        post.status = RidePost.FULL
        post.save()
        self.as_owner()
        self.act(post, ri, "undo")
        post.refresh_from_db()
        ri.refresh_from_db()
        self.assertEqual(post.status, RidePost.OPEN)
        self.assertEqual(ri.status, RideInterest.PENDING)
        self.assertEqual(post.seats_left(), 1)

    # Never more accepted than seats (sequential)
    def test_cannot_accept_past_capacity(self):
        post = self.post(seats=1)
        a = self.interest(post)
        b = self.interest(post, rider=self.rider2)
        self.as_owner()
        self.act(post, a, "accept")
        self.act(post, b, "accept")
        b.refresh_from_db()
        self.assertEqual(b.status, RideInterest.PENDING)
        self.assertEqual(post.interests.filter(status="accepted").count(), 1)

    # Only owner can act
    def test_non_owner_gets_404(self):
        post = self.post(seats=2)
        ri = self.interest(post, rider=self.rider2)
        r = self.act(post, ri, "accept")  # logged in as self.rider
        self.assertEqual(r.status_code, 404)
        ri.refresh_from_db()
        self.assertEqual(ri.status, RideInterest.PENDING)

    def test_get_not_allowed(self):
        post = self.post(seats=2)
        ri = self.interest(post)
        self.as_owner()
        r = self.client.get(reverse("rides:accept_interest", args=[post.pk, ri.pk]))
        self.assertEqual(r.status_code, 405)

    def test_interest_from_another_post_404(self):
        p1 = self.post(seats=2)
        p2 = self.post(owner=self.rider3, seats=2)
        ri = self.interest(p2)
        self.as_owner()
        self.assertEqual(self.act(p1, ri, "accept").status_code, 404)

    def test_declined_cannot_be_accepted(self):
        post = self.post(seats=2)
        ri = self.interest(post)
        self.as_owner()
        self.act(post, ri, "decline")
        self.act(post, ri, "accept")
        ri.refresh_from_db()
        self.assertEqual(ri.status, RideInterest.DECLINED)

    def test_cannot_accept_on_expired(self):
        post = self.post(seats=2, departure=at(TOMORROW, 9))
        ri = self.interest(post)
        RidePost.objects.filter(pk=post.pk).update(
            departure_at=at(TOMORROW, 9).replace(year=2025)
        )
        self.as_owner()
        self.act(post, ri, "accept")
        ri.refresh_from_db()
        self.assertEqual(ri.status, RideInterest.PENDING)

    # Rider sees updated status, "You're in" and others' names
    def test_accepted_rider_sees_youre_in_and_others(self):
        post = self.post(seats=2)
        self.interest(post, status=RideInterest.ACCEPTED)
        self.interest(post, rider=self.rider2, status=RideInterest.ACCEPTED)
        post.status = RidePost.FULL
        post.save()
        r = self.client.get(self.detail(post))
        self.assertContains(r, "You're in")
        self.assertContains(r, "Second Rider")
        self.assertNotContains(r, "r2@example.com")

    def test_pending_rider_does_not_see_accepted_names(self):
        post = self.post(seats=2)
        self.interest(post)
        self.interest(post, rider=self.rider2, status=RideInterest.ACCEPTED)
        r = self.client.get(self.detail(post))
        self.assertNotContains(r, "Second Rider")

    def test_accepted_rider_withdraw_reopens(self):
        post = self.post(seats=1)
        self.interest(post, status=RideInterest.ACCEPTED)
        post.status = RidePost.FULL
        post.save()
        self.withdraw(post)
        post.refresh_from_db()
        self.assertEqual(post.status, RidePost.OPEN)

    def test_closed_post_stays_closed_after_undo(self):
        post = self.post(seats=1, status=RidePost.CLOSED)
        ri = self.interest(post, status=RideInterest.ACCEPTED)
        self.as_owner()
        r = self.act(post, ri, "undo")
        post.refresh_from_db()
        self.assertEqual(post.status, RidePost.CLOSED)
        self.assertNotIn("open again", self.messages(r)[0])

    def test_undo_message_when_post_was_not_full(self):
        post = self.post(seats=3)
        ri = self.interest(post, status=RideInterest.ACCEPTED)
        self.as_owner()
        r = self.act(post, ri, "undo")
        self.assertNotIn("open again", self.messages(r)[0])

    def test_undo_after_departure_does_not_change_acceptance(self):
        post = self.post(seats=1, departure=at(TOMORROW, 9).replace(year=2025))
        ri = self.interest(post, status=RideInterest.ACCEPTED)
        post.status = RidePost.FULL
        post.save()
        self.as_owner()
        response = self.act(post, ri, "undo")
        ri.refresh_from_db()
        self.assertEqual(ri.status, RideInterest.ACCEPTED)
        self.assertEqual(self.messages(response), [ride_interest.EXPIRED])


class ConcurrentAcceptTests(TransactionTestCase):
    """Two accepts for the last seat at the same moment."""

    def test_two_simultaneous_accepts_take_one_seat(self):
        from zones.models import Zone
        from datetime import timedelta
        from django.utils import timezone

        users = get_user_model().objects
        owner = users.create_user("o@example.com", password=PASSWORD)
        a = users.create_user("a@example.com", password=PASSWORD)
        b = users.create_user("b@example.com", password=PASSWORD)
        z1 = Zone.objects.create(zone_id=161, name="M", borough="Manhattan")
        z2 = Zone.objects.create(zone_id=132, name="J", borough="Queens")
        post = RidePost.objects.create(
            owner=owner,
            pickup_zone=z1,
            dropoff_zone=z2,
            departure_at=timezone.now() + timedelta(days=1),
            seats=1,
        )
        ia = RideInterest.objects.create(post=post, rider=a)
        ib = RideInterest.objects.create(post=post, rider=b)
        barrier = threading.Barrier(2)
        results = []

        def go(ri):
            try:
                barrier.wait()
                results.append(
                    ride_interest.manage_owner_interest(
                        owner, post.pk, ri.pk, "accept"
                    )[1]
                )
            finally:
                connection.close()

        ts = [threading.Thread(target=go, args=(x,)) for x in (ia, ib)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(post.interests.filter(status=RideInterest.ACCEPTED).count(), 1)
