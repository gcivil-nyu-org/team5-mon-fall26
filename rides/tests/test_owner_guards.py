"""US34 #96 and US35 #97: interest actions that must change nothing."""

from django.http import Http404
from django.urls import reverse

from rides import interest as ride_interest
from rides.models import RideInterest, RidePost

from .test_show_interest import NOW, InterestTestData


class OwnerActionGuardTests(InterestTestData):
    def act(self, post, ri, action):
        name = {
            "accept": "accept_interest",
            "decline": "decline_interest",
            "undo": "undo_acceptance",
        }[action]
        self.client.force_login(self.owner)
        return self.client.post(reverse(f"rides:{name}", args=[post.pk, ri.pk]))

    def assert_unchanged(self, post, ri, action, status, message):
        response = self.act(post, ri, action)
        ri.refresh_from_db()
        self.assertEqual(ri.status, status)
        self.assertEqual(self.messages(response), [message])

    def test_accept_when_already_accepted(self):
        post = self.post(seats=2)
        ri = self.interest(post, status=RideInterest.ACCEPTED)
        self.assert_unchanged(
            post,
            ri,
            "accept",
            RideInterest.ACCEPTED,
            ride_interest.ALREADY_ACCEPTED,
        )

    def test_accept_on_closed_post(self):
        post = self.post(seats=2, status=RidePost.CLOSED)
        ri = self.interest(post)
        self.assert_unchanged(
            post, ri, "accept", RideInterest.PENDING, ride_interest.CLOSED
        )

    def test_decline_twice(self):
        post = self.post(seats=2)
        ri = self.interest(post, status=RideInterest.DECLINED)
        self.assert_unchanged(
            post,
            ri,
            "decline",
            RideInterest.DECLINED,
            ride_interest.ALREADY_DECLINED,
        )

    def test_decline_an_accepted_rider(self):
        post = self.post(seats=2)
        ri = self.interest(post, status=RideInterest.ACCEPTED)
        self.assert_unchanged(
            post, ri, "decline", RideInterest.ACCEPTED, ride_interest.NOT_PENDING
        )

    def test_undo_a_pending_rider(self):
        post = self.post(seats=2)
        ri = self.interest(post)
        self.assert_unchanged(
            post, ri, "undo", RideInterest.PENDING, ride_interest.NOT_ACCEPTED
        )

    def test_unknown_action_is_an_error(self):
        post = self.post(seats=2)
        ri = self.interest(post)
        with self.assertRaises(ValueError):
            ride_interest.manage_owner_interest(self.owner, post.pk, ri.pk, "maybe")

    def test_deleted_post_rejects_interest_actions_and_detail_views(self):
        post = self.post(status=RidePost.DELETED)
        ri = self.interest(post)

        self.assertEqual(
            ride_interest.blocked_reason(post, self.rider, NOW), ride_interest.DELETED
        )
        with self.assertRaises(Http404):
            ride_interest.manage_owner_interest(self.owner, post.pk, ri.pk, "accept")
        with self.assertRaises(Http404):
            ride_interest.withdraw_interest(self.rider, post.pk)
        self.assertFalse(ride_interest.can_view(post, self.owner, NOW))

        self.assertEqual(self.client.get(self.detail(post)).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.detail(post)).status_code, 404)
