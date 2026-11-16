"""US35 #97: Edit, Close, or Delete My Post."""

from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import Profile
from rides.forms import TOO_FEW_SEATS
from rides.models import RideInterest, RidePost
from rides.search import find_rides

from .test_show_interest import PASSWORD, TOMORROW, InterestTestData, at


class EditCloseDeleteTests(InterestTestData):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        users = get_user_model().objects
        cls.rider2 = users.create_user("r2@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.rider2, display_name="Second Rider")
        cls.searcher = users.create_user("r3@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.searcher, display_name="Searcher")

    def as_owner(self):
        self.client.force_login(self.owner)

    def edit(self, post, **overrides):
        data = {
            "departure_at": "2026-11-12T10:00",
            "seats": "2",
            "note": "",
        }
        data.update(overrides)
        return self.client.post(reverse("rides:edit_ride", args=[post.pk]), data)

    def close(self, post):
        return self.client.post(reverse("rides:close_ride", args=[post.pk]))

    def delete(self, post):
        return self.client.post(reverse("rides:delete_ride", args=[post.pk]))

    def in_search(self, post):
        results = find_rides(self.searcher, self.midtown, self.jfk, TOMORROW)
        return post.pk in [m.post.pk for m in results]

    # The owner can edit an open post, with the same rules as when posting
    def test_owner_edits_time_seats_and_note(self):
        post = self.post(seats=2)
        self.as_owner()
        r = self.edit(post, seats="3", note="Meet at the corner")
        self.assertRedirects(r, self.detail(post))
        post.refresh_from_db()
        self.assertEqual(post.departure_at, at(TOMORROW, 10))
        self.assertEqual(post.seats, 3)
        self.assertEqual(post.note, "Meet at the corner")

    def test_edit_uses_posting_rules(self):
        post = self.post(seats=2)
        self.as_owner()
        for bad in (
            {"departure_at": "2026-11-10T10:00"},  # in the past
            {"departure_at": "2026-12-01T10:00"},  # more than 14 days ahead
            {"departure_at": "2026-11-12T10:05"},  # not a 15-minute step
            {"seats": "4"},
            {"note": "call me on 212-555-0100"},
        ):
            with self.subTest(bad=bad):
                r = self.edit(post, **bad)
                self.assertEqual(r.status_code, 200)
        post.refresh_from_db()
        self.assertEqual(post.departure_at, at(TOMORROW, 9))

    def test_edit_cannot_change_zones(self):
        post = self.post(seats=2)
        self.as_owner()
        self.edit(post, pickup_zone=self.jfk.pk, dropoff_zone=self.midtown.pk)
        post.refresh_from_db()
        self.assertEqual(post.pickup_zone_id, self.midtown.pk)

    # Seats can't be set lower than the riders already accepted
    def test_seats_cannot_go_below_accepted(self):
        post = self.post(seats=3)
        self.interest(post, status=RideInterest.ACCEPTED)
        self.interest(post, rider=self.rider2, status=RideInterest.ACCEPTED)
        self.as_owner()
        r = self.edit(post, seats="1")
        self.assertContains(r, TOO_FEW_SEATS)
        post.refresh_from_db()
        self.assertEqual(post.seats, 3)

    def test_seats_equal_to_accepted_makes_post_full(self):
        post = self.post(seats=3)
        self.interest(post, status=RideInterest.ACCEPTED)
        self.as_owner()
        self.edit(post, seats="1")
        post.refresh_from_db()
        self.assertEqual(post.status, RidePost.FULL)
        self.assertFalse(self.in_search(post))

    # A closed post disappears from search but stays visible to the owner
    # and accepted riders
    def test_closed_post_hidden_from_search_but_visible(self):
        post = self.post(seats=2)
        self.interest(post, status=RideInterest.ACCEPTED)
        self.as_owner()
        self.close(post)
        post.refresh_from_db()
        self.assertEqual(post.status, RidePost.CLOSED)
        self.assertFalse(self.in_search(post))
        self.assertEqual(self.client.get(self.detail(post)).status_code, 200)
        self.client.force_login(self.rider)
        self.assertEqual(self.client.get(self.detail(post)).status_code, 200)
        self.client.force_login(self.searcher)
        self.assertEqual(self.client.get(self.detail(post)).status_code, 404)

    def test_closed_post_blocks_new_interest(self):
        post = self.post(seats=2, status=RidePost.CLOSED)
        self.client.force_login(self.searcher)
        self.client.post(reverse("rides:show_interest", args=[post.pk]))
        self.assertFalse(post.interests.exists())

    # A deleted post is removed for everyone, and interested riders see
    # that it was deleted
    def test_delete_asks_for_confirmation_first(self):
        post = self.post(seats=2)
        self.as_owner()
        r = self.client.get(reverse("rides:delete_ride", args=[post.pk]))
        self.assertContains(r, "Delete shared ride?")
        post.refresh_from_db()
        self.assertEqual(post.status, RidePost.OPEN)

    def test_deleted_post_is_gone_for_everyone(self):
        post = self.post(seats=2, note="Blue umbrella")
        self.interest(post)
        self.as_owner()
        self.delete(post)
        post.refresh_from_db()
        self.assertEqual(post.status, RidePost.DELETED)
        self.assertEqual(post.note, "")
        self.assertFalse(self.in_search(post))
        for user in (self.owner, self.rider, self.searcher):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.detail(post)).status_code, 404)

    def test_interested_rider_sees_deleted_notice(self):
        post = self.post(seats=2)
        self.interest(post)
        self.as_owner()
        self.delete(post)
        self.client.force_login(self.rider)
        r = self.client.get(reverse("rides:my_rides"))  # moved there in US37
        self.assertContains(r, "This shared ride was deleted.")

    def test_deleted_post_frees_an_open_post_slot(self):
        posts = [self.post(departure=at(TOMORROW, 9 + h)) for h in range(3)]
        self.as_owner()
        self.delete(posts[0])
        r = self.client.post(
            reverse("rides:post_ride"),
            {
                "pickup_zone": self.midtown.pk,
                "dropoff_zone": self.jfk.pk,
                "departure_at": "2026-11-12T15:00",
                "seats": "1",
                "note": "",
            },
        )
        self.assertEqual(r.status_code, 302)

    # Only the owner can edit, close or delete the post
    def test_non_owner_gets_404_everywhere(self):
        post = self.post(seats=2)
        self.client.force_login(self.searcher)
        self.assertEqual(self.edit(post).status_code, 404)
        self.assertEqual(self.close(post).status_code, 404)
        self.assertEqual(self.delete(post).status_code, 404)
        get_delete = self.client.get(reverse("rides:delete_ride", args=[post.pk]))
        self.assertEqual(get_delete.status_code, 404)
        post.refresh_from_db()
        self.assertEqual(post.status, RidePost.OPEN)

    def test_close_needs_post(self):
        post = self.post(seats=2)
        self.as_owner()
        r = self.client.get(reverse("rides:close_ride", args=[post.pk]))
        self.assertEqual(r.status_code, 405)
