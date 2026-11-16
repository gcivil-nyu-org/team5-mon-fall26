"""US37 #99: My Rides."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import Profile
from rides import my_rides
from rides.models import RideInterest, RideMessage, RidePost

from .test_show_interest import NOW, PASSWORD, TOMORROW, InterestTestData, at

MY_RIDES = reverse("rides:my_rides")


class MyRidesTestData(InterestTestData):
    """self.owner (Early Bird) posts; self.rider (Night Owl) asks to join.
    The client starts signed in as self.rider."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        users = get_user_model().objects
        cls.rider2 = users.create_user("r2@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.rider2, display_name="Second Rider")
        cls.stranger = users.create_user("stranger@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.stranger, display_name="Stranger")

    def message(self, post, sender, receiver, text="Hi", read=False):
        return RideMessage.objects.create(
            post=post,
            sender=sender,
            receiver=receiver,
            text=text,
            read_at=NOW if read else None,
        )

    def page(self, user=None, **params):
        if user is not None:
            self.client.force_login(user)
        return self.client.get(MY_RIDES, params)

    def conversation(self, post, rider):
        return reverse("rides:conversation", args=[post.pk, rider.pk])


class AccessTests(MyRidesTestData):
    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        response = self.client.get(MY_RIDES)
        self.assertRedirects(
            response,
            f"{reverse('accounts:signin')}?next={MY_RIDES}",
            fetch_redirect_response=False,
        )

    def test_rider_without_a_display_name_chooses_one_first(self):
        nameless = get_user_model().objects.create_user("n@example.com", password="x")
        self.client.force_login(nameless)
        response = self.client.get(MY_RIDES)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:display_name"), response.url)

    def test_page_uses_display_names_never_email(self):
        post = self.post()
        self.interest(post)
        for user in (self.owner, self.rider):
            with self.subTest(user=user.email):
                response = self.page(user)
                # These test users' addresses are stored as their usernames.
                self.assertNotContains(response, "@example.com")


class MyPostsTests(MyRidesTestData):
    """My posts: status, seats left and interested riders."""

    def test_lists_own_posts_with_status_seats_and_riders(self):
        post = self.post(seats=3)
        self.interest(post, status=RideInterest.ACCEPTED)
        self.interest(post, rider=self.rider2)
        response = self.page(self.owner)
        rows = response.context["my_posts"]
        self.assertEqual([r.post for r in rows], [post])
        self.assertEqual(rows[0].status, "Open")
        self.assertEqual(rows[0].seats_left, 2)
        self.assertEqual(
            [(r.name, r.status) for r in rows[0].riders],
            [("Night Owl", "Accepted"), ("Second Rider", "Pending")],
        )
        self.assertContains(response, "2 seats left of 3")
        self.assertContains(response, "Night Owl")

    def test_full_closed_and_expired_posts_show_their_status(self):
        full = self.post(seats=1, status=RidePost.FULL)
        closed = self.post(departure=at(TOMORROW, 10), status=RidePost.CLOSED)
        expired = self.post(departure=NOW - timedelta(hours=2))
        rows = {r.post: r.status for r in self.page(self.owner).context["my_posts"]}
        self.assertEqual(rows, {full: "Full", closed: "Closed", expired: "Expired"})

    def test_deleted_posts_and_other_riders_posts_are_left_out(self):
        self.post(status=RidePost.DELETED)
        self.post(owner=self.rider2)
        self.assertEqual(self.page(self.owner).context["my_posts"], [])

    def test_upcoming_soonest_first_then_past_latest_first(self):
        later = self.post(departure=at(TOMORROW, 18))
        sooner = self.post(departure=at(TOMORROW, 9))
        past = self.post(departure=NOW - timedelta(days=1))
        older = self.post(departure=NOW - timedelta(days=3))
        rows = self.page(self.owner).context["my_posts"]
        self.assertEqual([r.post for r in rows], [sooner, later, past, older])

    def test_rider_who_withdrew_but_has_messages_is_listed(self):
        post = self.post()
        self.message(post, self.rider, self.owner, "Sorry, plans changed")
        rows = self.page(self.owner).context["my_posts"]
        self.assertEqual(
            [(r.name, r.status, r.unread) for r in rows[0].riders],
            [("Night Owl", "Withdrawn", 1)],
        )


class AskedRidesTests(MyRidesTestData):
    """Rides I've asked to join: pending, accepted, declined, closed, deleted."""

    def test_each_status(self):
        cases = {
            "Pending": dict(),
            "Accepted": dict(status=RideInterest.ACCEPTED),
            "Declined": dict(status=RideInterest.DECLINED),
            "Closed": dict(post_status=RidePost.CLOSED),
            "Deleted": dict(post_status=RidePost.DELETED),
        }
        posts = {}
        for hour, (label, fields) in enumerate(cases.items(), start=9):
            post = self.post(
                departure=at(TOMORROW, hour),
                status=fields.pop("post_status", RidePost.OPEN),
            )
            self.interest(post, **fields)
            posts[post] = label
        rows = self.page().context["asked_rides"]
        self.assertEqual({r.post: r.status for r in rows}, posts)
        response = self.page()
        self.assertContains(response, "This shared ride was deleted.")
        self.assertContains(response, "This shared ride was closed.")

    def test_deleted_ride_has_no_detail_link_but_keeps_its_messages(self):
        post = self.post(status=RidePost.DELETED)
        self.interest(post)
        response = self.page()
        detail = reverse("rides:ride_detail", args=[post.pk])
        self.assertNotContains(response, f'href="{detail}"')
        self.assertContains(response, f'href="{self.conversation(post, self.rider)}"')

    def test_shows_owner_name_and_only_my_requests(self):
        mine = self.post()
        self.interest(mine)
        others = self.post(departure=at(TOMORROW, 11))
        self.interest(others, rider=self.rider2)
        response = self.page()
        self.assertEqual([r.post for r in response.context["asked_rides"]], [mine])
        self.assertContains(response, "Posted by Early Bird")

    def test_own_posts_are_not_in_asked_rides(self):
        post = self.post(owner=self.rider)
        self.message(post, self.owner, self.rider, read=True)
        self.assertEqual(self.page().context["asked_rides"], [])

    def test_withdrawn_ride_with_messages_is_listed(self):
        post = self.post()
        self.message(post, self.owner, self.rider, "Still coming?")
        rows = self.page().context["asked_rides"]
        self.assertEqual(
            [(r.status, r.unread, r.detail_url) for r in rows], [("Withdrawn", 1, None)]
        )


class UnreadTests(MyRidesTestData):
    """Unread counts per conversation, cleared when it is opened."""

    def test_unread_count_for_each_conversation(self):
        post = self.post()
        self.interest(post)
        self.interest(post, rider=self.rider2)
        self.message(post, self.rider, self.owner, "one")
        self.message(post, self.rider, self.owner, "two")
        self.message(post, self.rider2, self.owner, "read already", read=True)
        self.message(post, self.owner, self.rider, "mine, not unread for me")
        response = self.page(self.owner)
        riders = response.context["my_posts"][0].riders
        self.assertEqual(
            [(r.name, r.unread) for r in riders],
            [("Night Owl", 2), ("Second Rider", 0)],
        )
        self.assertContains(response, "2 unread")

    def test_rider_sees_unread_messages_from_the_owner(self):
        post = self.post()
        self.interest(post)
        self.message(post, self.owner, self.rider, "Meet at gate 4?")
        response = self.page()
        self.assertEqual(response.context["asked_rides"][0].unread, 1)
        self.assertContains(response, "1 unread")

    def test_opening_the_conversation_clears_the_count(self):
        post = self.post()
        self.interest(post)
        self.message(post, self.owner, self.rider, "Meet at gate 4?")
        self.client.get(self.conversation(post, self.rider))
        response = self.page()
        self.assertEqual(response.context["asked_rides"][0].unread, 0)
        self.assertNotContains(response, "unread")

    def test_opening_one_conversation_leaves_the_others_unread(self):
        post = self.post()
        self.interest(post)
        self.interest(post, rider=self.rider2)
        self.message(post, self.rider, self.owner)
        self.message(post, self.rider2, self.owner)
        self.client.force_login(self.owner)
        self.client.get(self.conversation(post, self.rider))
        riders = self.page().context["my_posts"][0].riders
        self.assertEqual([r.unread for r in riders], [0, 1])


class BadgeTests(MyRidesTestData):
    """The nav badge: unread messages plus new interested riders."""

    def badge(self, page=MY_RIDES):
        response = self.client.get(page)
        return response, response.context["ride_badge"].count

    def test_no_badge_when_there_is_nothing_new(self):
        response, count = self.badge()
        self.assertEqual(count, 0)
        self.assertContains(response, 'id="my-rides-link"')
        self.assertNotContains(response, "nav-badge")

    def test_counts_unread_messages_and_new_interested_riders(self):
        post = self.post()
        self.interest(post)  # new for the owner
        self.interest(post, rider=self.rider2, owner_seen_at=NOW)  # seen
        self.message(post, self.rider2, self.owner)
        self.message(post, self.rider2, self.owner)
        self.client.force_login(self.owner)
        response, count = self.badge()
        self.assertEqual(count, 3)
        self.assertContains(
            response, '<span class="nav-badge" aria-hidden="true">3</span>', html=True
        )
        self.assertContains(response, "New")

    def test_showing_interest_makes_the_owner_badge_appear(self):
        post = self.post()
        self.client.post(reverse("rides:show_interest", args=[post.pk]))
        self.client.force_login(self.owner)
        self.assertEqual(self.badge()[1], 1)

    def test_opening_the_post_page_clears_new_interested_riders(self):
        post = self.post()
        self.interest(post)
        self.client.force_login(self.owner)
        detail = self.client.get(self.detail(post))
        self.assertContains(detail, '<span class="new-tag">New</span>', html=True)
        response, count = self.badge()
        self.assertEqual(count, 0)
        self.assertNotContains(response, "nav-badge")
        self.assertFalse(
            RideInterest.objects.filter(owner_seen_at__isnull=True).exists()
        )

    def test_another_rider_opening_the_post_does_not_clear_it(self):
        post = self.post()
        self.interest(post)
        self.client.force_login(self.rider2)
        self.client.get(self.detail(post))
        self.assertEqual(my_rides.badge_count(self.owner), 1)

    def test_reading_the_messages_clears_the_badge(self):
        post = self.post()
        self.interest(post)
        self.message(post, self.owner, self.rider)
        self.assertEqual(self.badge()[1], 1)
        self.client.get(self.conversation(post, self.rider))
        self.assertEqual(self.badge()[1], 0)

    def test_badge_is_on_the_map_and_other_pages(self):
        post = self.post()
        self.interest(post)
        self.message(post, self.owner, self.rider)
        for name in (
            "zones:map",
            "zones:compare",
            "rides:find_rides",
            "routes:my_routes",
        ):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'id="my-rides-link"')
                self.assertContains(
                    response,
                    '<span class="nav-badge" aria-hidden="true">1</span>',
                    html=True,
                )

    def test_guests_get_the_link_without_a_badge(self):
        self.client.logout()
        response = self.client.get(reverse("zones:map"))
        self.assertContains(response, 'id="my-rides-link"')
        self.assertNotIn("ride_badge", response.context)

    def test_owner_deleted_posts_do_not_count(self):
        post = self.post(status=RidePost.DELETED)
        self.interest(post)
        self.message(post, self.rider, self.owner)
        self.assertEqual(my_rides.badge_count(self.owner), 0)

    def test_badge_only_counts_my_own_items(self):
        post = self.post()
        self.interest(post)
        self.message(post, self.rider, self.owner)
        self.assertEqual(my_rides.badge_count(self.stranger), 0)
        self.assertEqual(my_rides.badge_count(self.rider), 0)
        self.assertEqual(my_rides.badge_count(self.owner), 2)


class PastRidesTests(MyRidesTestData):
    """Rides more than 7 days in the past are hidden unless asked for."""

    def setUp(self):
        super().setUp()
        self.recent = self.post(departure=NOW - timedelta(days=6, hours=23))
        self.old = self.post(departure=NOW - timedelta(days=7, minutes=1))
        for post in (self.recent, self.old):
            self.interest(post, owner_seen_at=NOW)

    def test_old_rides_are_hidden_by_default(self):
        for user, key in ((self.owner, "my_posts"), (self.rider, "asked_rides")):
            with self.subTest(list=key):
                response = self.page(user)
                self.assertEqual([r.post for r in response.context[key]], [self.recent])
                self.assertEqual(response.context["hidden_count"], 1)
                self.assertContains(response, "Show past rides")
                self.assertContains(response, "(1 hidden)")

    def test_show_past_rides_shows_them(self):
        for user, key in ((self.owner, "my_posts"), (self.rider, "asked_rides")):
            with self.subTest(list=key):
                response = self.page(user, past="1")
                self.assertEqual(
                    [r.post for r in response.context[key]], [self.recent, self.old]
                )
                self.assertContains(response, "Hide past rides")

    def test_an_old_ride_with_unread_messages_stays_visible(self):
        self.message(self.old, self.rider, self.owner, "Thanks for the ride!")
        rows = self.page(self.owner).context["my_posts"]
        self.assertIn(self.old, [r.post for r in rows])


class MovedRideUpdatesTests(MyRidesTestData):
    """US35's "Your ride updates" moved from /rides/ to My rides."""

    def test_find_rides_links_to_my_rides(self):
        response = self.client.get(reverse("rides:find_rides"))
        self.assertContains(response, f'href="{MY_RIDES}"')
        self.assertNotContains(response, "Your ride updates")
