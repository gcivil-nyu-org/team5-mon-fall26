"""US31 #93: Post a Ride-Share Offer."""

from datetime import datetime, timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from accounts.models import Profile
from rides import forms as ride_forms
from rides.forms import RidePostForm, default_departure
from rides.models import MAX_OPEN_POSTS, RidePost
from zones.models import Zone
from zones.views import NYC_TZ

PASSWORD = "a-strong-test-password-31"
# A fixed moment for the form tests: Tuesday 11 Nov 2026, 13:07:30 in New York.
NOW = datetime(2026, 11, 11, 13, 7, 30, tzinfo=NYC_TZ)


def local_input(moment):
    """A datetime-local value, as the browser sends it (New York time)."""
    return moment.astimezone(NYC_TZ).strftime("%Y-%m-%dT%H:%M")


def next_quarter(moment, days=0, hours=0):
    """A quarter hour after moment, plus days and hours."""
    moment = moment.astimezone(NYC_TZ) + timedelta(days=days, hours=hours)
    moment = moment.replace(second=0, microsecond=0)
    return moment + timedelta(minutes=15 - moment.minute % 15)


class RideTestData(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.user = users.create_user("alex.k@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.user, display_name="Night Owl")
        cls.other = users.create_user("sam@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.other, display_name="Early Bird")
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

    def make_post(self, owner=None, departure=None, **fields):
        return RidePost.objects.create(
            owner=owner or self.user,
            pickup_zone=fields.pop("pickup_zone", self.midtown),
            dropoff_zone=fields.pop("dropoff_zone", self.jfk),
            departure_at=departure or next_quarter(timezone.now(), days=1),
            seats=fields.pop("seats", 2),
            **fields,
        )

    def data(self, departure, **overrides):
        data = {
            "pickup_zone": self.midtown.pk,
            "dropoff_zone": self.jfk.pk,
            "departure_at": local_input(departure),
            "seats": "2",
            "note": "",
        }
        data.update(overrides)
        return data


class ModelTests(RideTestData):
    def test_new_posts_are_open_with_a_created_date(self):
        post = self.make_post()

        self.assertEqual(post.status, RidePost.OPEN)
        self.assertIsNotNone(post.created_at)
        self.assertEqual(post.status_label(), "Open")

    def test_text(self):
        post = self.make_post()
        departure = f"{post.departure_at:%Y-%m-%d %H:%M}"
        self.assertEqual(
            str(post), f"Midtown Center → JFK Airport at {departure} (Open)"
        )

    def test_a_post_whose_departure_has_passed_is_expired(self):
        now = timezone.now()
        post = self.make_post(departure=now - timedelta(minutes=1))

        self.assertTrue(post.is_expired(now))
        self.assertEqual(post.status_label(now), "Expired")

    def test_the_departure_moment_itself_counts_as_expired(self):
        now = timezone.now()
        post = self.make_post(departure=now)
        self.assertEqual(post.status_label(now), "Expired")
        self.assertEqual(post.status_label(now - timedelta(seconds=1)), "Open")

    def test_full_posts_expire_too_and_closed_posts_stay_closed(self):
        past = timezone.now() - timedelta(hours=1)
        full = self.make_post(departure=past, status=RidePost.FULL)
        closed = self.make_post(departure=past, status=RidePost.CLOSED)
        self.assertEqual(full.status_label(), "Expired")
        self.assertEqual(closed.status_label(), "Closed")
        later = timezone.now() + timedelta(days=1)
        self.assertEqual(
            self.make_post(departure=later, status="full").status_label(), "Full"
        )
        self.assertEqual(
            self.make_post(departure=later, status="closed").status_label(), "Closed"
        )

    def test_open_means_open_and_not_yet_departed(self):
        now = timezone.now()
        future = now + timedelta(days=1)
        open_post = self.make_post(departure=future)
        self.make_post(departure=now - timedelta(minutes=1))  # expired
        self.make_post(departure=future, status=RidePost.FULL)
        self.make_post(departure=future, status=RidePost.CLOSED)

        self.assertEqual(list(RidePost.objects.open(now)), [open_post])
        self.assertEqual(list(RidePost.objects.open()), [open_post])

    def test_database_refuses_seats_outside_1_to_3(self):
        for seats in (0, 4):
            with self.subTest(seats=seats):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.make_post(seats=seats)

    def test_database_refuses_the_same_pickup_and_dropoff(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_post(dropoff_zone=self.midtown)

    def test_database_refuses_an_unknown_status(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_post(status="maybe")

    def test_deleting_the_account_deletes_the_users_posts(self):
        self.make_post()
        self.make_post(owner=self.other)

        self.user.delete()

        self.assertEqual(
            list(RidePost.objects.values_list("owner", flat=True)), [self.other.pk]
        )

    def test_posts_are_in_the_admin(self):
        self.assertTrue(admin.site.is_registered(RidePost))


class FormTests(RideTestData):
    def form(self, departure=None, user=None, now=NOW, **overrides):
        departure = departure or next_quarter(now, days=1)
        return RidePostForm(
            user or self.user, self.data(departure, **overrides), now=now
        )

    def assert_error(self, form, field, message):
        self.assertFalse(form.is_valid())
        self.assertIn(message, form.errors[field])

    def test_a_valid_post(self):
        form = self.form(note="  Leaving from the north side of the block.  ")
        self.assertTrue(form.is_valid(), form.errors)
        post = form.save()

        self.assertEqual(post.owner, self.user)
        self.assertEqual(post.status, RidePost.OPEN)
        self.assertEqual(post.seats, 2)
        self.assertEqual(post.note, "Leaving from the north side of the block.")
        self.assertEqual(post.departure_at, next_quarter(NOW, days=1))

    def test_departure_is_new_york_time(self):
        form = self.form(departure_at="2026-11-12T18:30")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["departure_at"],
            datetime(2026, 11, 12, 18, 30, tzinfo=NYC_TZ),
        )

    def test_the_owner_and_status_never_come_from_the_request(self):
        form = self.form(owner=self.other.pk, status="closed")
        self.assertTrue(form.is_valid(), form.errors)
        post = form.save()
        self.assertEqual((post.owner, post.status), (self.user, RidePost.OPEN))

    def test_the_same_pickup_and_dropoff_is_rejected(self):
        form = self.form(dropoff_zone=self.midtown.pk)
        self.assert_error(form, "dropoff_zone", ride_forms.SAME_ZONES)

    def test_a_departure_in_the_past_is_rejected(self):
        for departure in ("2026-11-11T13:00", "2026-11-10T09:00"):
            with self.subTest(departure=departure):
                form = self.form(departure_at=departure)
                self.assert_error(form, "departure_at", ride_forms.DEPARTURE_PAST)

    def test_the_next_quarter_hour_is_allowed(self):
        form = self.form(departure_at="2026-11-11T13:15")
        self.assertTrue(form.is_valid(), form.errors)

    def test_more_than_14_days_ahead_is_rejected(self):
        form = self.form(departure_at="2026-11-25T13:15")
        self.assert_error(form, "departure_at", ride_forms.DEPARTURE_TOO_FAR)

    def test_up_to_14_days_ahead_is_allowed(self):
        # 14 days after 13:07:30 is 13:07:30; 13:00 is the last quarter hour.
        form = self.form(departure_at="2026-11-25T13:00")
        self.assertTrue(form.is_valid(), form.errors)

    def test_departures_must_be_on_a_quarter_hour(self):
        for minute in ("07", "20", "59"):
            with self.subTest(minute=minute):
                form = self.form(departure_at=f"2026-11-12T10:{minute}")
                self.assert_error(form, "departure_at", ride_forms.DEPARTURE_STEP)

    def test_a_departure_is_required(self):
        form = self.form(departure_at="")
        self.assert_error(form, "departure_at", ride_forms.DEPARTURE_REQUIRED)

    def test_seats_are_1_to_3(self):
        for seats in ("1", "2", "3"):
            with self.subTest(seats=seats):
                self.assertTrue(self.form(seats=seats).is_valid())
        for seats in ("0", "4", "x", ""):
            with self.subTest(seats=seats):
                self.assertFalse(self.form(seats=seats).is_valid())
                self.assertIn("seats", self.form(seats=seats).errors)

    def test_zones_must_be_on_the_map(self):
        form = self.form(pickup_zone=self.unknown.pk)
        self.assertFalse(form.is_valid())
        self.assertIn("pickup_zone", form.errors)
        choices = [value for value, _ in form.fields["pickup_zone"].choices if value]
        self.assertNotIn(264, [int(str(value)) for value in choices])

    def test_the_note_is_optional_and_at_most_200_characters(self):
        self.assertTrue(self.form(note="").is_valid())
        self.assertTrue(self.form(note="x" * 200).is_valid())
        self.assert_error(self.form(note="x" * 201), "note", ride_forms.NOTE_TOO_LONG)

    def test_the_note_warns_against_contact_details(self):
        help_text = RidePostForm(self.user, now=NOW).fields["note"].help_text
        self.assertIn("addresses, phone numbers", help_text)
        self.assertIn("Other riders will see", help_text)

    def test_contact_details_in_the_note_are_rejected(self):
        for note in (
            "Email me at alex.k@example.com",
            "call 212-555-0100",
            "text +1 (212) 555 0100 when close",
            "2125550100",
        ):
            with self.subTest(note=note):
                self.assert_error(self.form(note=note), "note", ride_forms.NOTE_CONTACT)

    def test_ordinary_numbers_in_the_note_are_fine(self):
        note = "Flight UA 1234 lands at 10:30, terminal 4, 2 bags"
        self.assertTrue(self.form(note=note).is_valid())

    def test_a_4th_open_post_is_rejected(self):
        for _ in range(MAX_OPEN_POSTS):
            self.make_post(departure=next_quarter(NOW, days=2))

        form = self.form()

        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(), [ride_forms.TOO_MANY_OPEN])

    def test_expired_full_closed_and_other_riders_posts_do_not_count(self):
        later = next_quarter(NOW, days=2)
        self.make_post(departure=NOW - timedelta(minutes=1))  # expired
        self.make_post(departure=later, status=RidePost.FULL)
        self.make_post(departure=later, status=RidePost.CLOSED)
        self.make_post(departure=later)
        self.make_post(departure=later)
        for _ in range(MAX_OPEN_POSTS):
            self.make_post(owner=self.other, departure=later)

        form = self.form()

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNotNone(form.save())

    def test_a_4th_open_post_saved_meanwhile_is_rejected(self):
        # Two posts sent at the same moment: both pass the check, the save
        # counts again with the rider's row locked.
        form = self.form()
        self.assertTrue(form.is_valid())
        for _ in range(MAX_OPEN_POSTS):
            self.make_post(departure=next_quarter(NOW, days=2))

        self.assertIsNone(form.save())

        self.assertEqual(form.non_field_errors(), [ride_forms.TOO_MANY_OPEN])
        self.assertEqual(RidePost.objects.count(), MAX_OPEN_POSTS)

    def test_the_default_departure_is_a_quarter_hour_at_least_15_minutes_away(self):
        cases = {
            datetime(2026, 11, 11, 13, 7, 30, tzinfo=NYC_TZ): (13, 30),
            datetime(2026, 11, 11, 13, 0, 0, tzinfo=NYC_TZ): (13, 15),
            datetime(2026, 11, 11, 13, 0, 1, tzinfo=NYC_TZ): (13, 30),
            datetime(2026, 11, 11, 23, 50, 0, tzinfo=NYC_TZ): (0, 15),
        }
        for now, (hour, minute) in cases.items():
            with self.subTest(now=now):
                departure = default_departure(now).astimezone(NYC_TZ)
                self.assertEqual((departure.hour, departure.minute), (hour, minute))
                self.assertEqual((departure.second, departure.microsecond), (0, 0))

    def test_the_departure_picker_steps_15_minutes_within_the_next_14_days(self):
        attrs = RidePostForm(self.user, now=NOW).fields["departure_at"].widget.attrs
        self.assertEqual(attrs["step"], "900")
        self.assertEqual(attrs["min"], "2026-11-11T13:15")
        self.assertEqual(attrs["max"], "2026-11-25T13:00")


class PostRidePageTests(RideTestData):
    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("rides:post_ride")
        self.departure = next_quarter(timezone.now(), days=1)

    def post(self, **overrides):
        return self.client.post(self.url, self.data(self.departure, **overrides))

    def test_the_form_opens_with_the_route_filled_in(self):
        response = self.client.get(self.url, {"from": 161, "to": 237})

        self.assertContains(response, "Post a shared ride")
        self.assertContains(response, '<option value="161" selected>')
        self.assertContains(response, '<option value="237" selected>')
        self.assertContains(response, 'step="900"')
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "Don&#x27;t include addresses, phone numbers")

    def test_bad_zone_ids_in_the_address_are_ignored(self):
        response = self.client.get(self.url, {"from": "x", "to": "999999999999"})
        self.assertEqual(response.status_code, 200)
        initial = response.context["form"].initial
        self.assertEqual(
            (initial["pickup_zone"], initial["dropoff_zone"]), (None, None)
        )

    def test_a_rider_with_a_display_name_posts_a_ride_and_it_is_open(self):
        response = self.post(seats="3", note="Two bags")

        post = RidePost.objects.get()
        detail = reverse("rides:ride_detail", args=[post.pk])
        self.assertRedirects(response, detail, fetch_redirect_response=False)
        page = self.client.get(detail)
        self.assertContains(page, "Your shared ride is posted.")
        self.assertContains(page, '<span class="status status-open">Open</span>')
        self.assertContains(page, "Night Owl")
        self.assertContains(page, "Midtown Center (Manhattan)")
        self.assertContains(page, "JFK Airport (Queens)")
        self.assertContains(page, self.departure.strftime("%a %-d %b %Y"))
        self.assertContains(page, "Two bags")
        self.assertContains(page, "3 seats")

    def test_a_rejected_post_shows_the_reason_and_saves_nothing(self):
        cases = {
            ride_forms.SAME_ZONES: {"dropoff_zone": self.midtown.pk},
            ride_forms.DEPARTURE_PAST: {
                "departure_at": local_input(timezone.now() - timedelta(hours=1))
            },
            ride_forms.DEPARTURE_TOO_FAR: {
                "departure_at": local_input(next_quarter(timezone.now(), days=15))
            },
        }
        for message, overrides in cases.items():
            with self.subTest(message=message):
                response = self.post(**overrides)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message.replace("'", "&#x27;"))
        self.assertFalse(RidePost.objects.exists())

    def test_a_4th_open_post_is_rejected_with_a_message(self):
        for _ in range(MAX_OPEN_POSTS):
            self.make_post()

        response = self.post()

        self.assertContains(response, ride_forms.TOO_MANY_OPEN)
        self.assertEqual(RidePost.objects.count(), MAX_OPEN_POSTS)

    def test_guests_see_a_sign_in_prompt_in_place_of_the_form(self):
        self.client.logout()

        response = self.client.get(self.url, {"from": 161, "to": 237})

        signin = (
            reverse("accounts:signin")
            + "?"
            + urlencode({"next": f"{self.url}?from=161&to=237"})
        )
        self.assertContains(response, "Sign in to share a ride")
        self.assertContains(response, f'href="{signin.replace("&", "&amp;")}"')
        self.assertNotContains(response, "<form")

    def test_a_guest_post_creates_nothing(self):
        self.client.logout()

        response = self.post()

        self.assertContains(response, "Sign in to share a ride")
        self.assertFalse(RidePost.objects.exists())

    def test_a_rider_without_a_display_name_chooses_one_first_then_comes_back(self):
        Profile.objects.filter(user=self.user).delete()
        form_page = f"{self.url}?from=161&to=237"

        response = self.client.get(form_page)

        choose = reverse("accounts:display_name") + "?" + urlencode({"next": form_page})
        self.assertRedirects(response, choose)
        response = self.client.post(
            reverse("accounts:display_name"),
            {"display_name": "Night Owl", "next": form_page},
        )
        self.assertRedirects(response, form_page)

    def test_posting_without_a_display_name_saves_nothing(self):
        Profile.objects.filter(user=self.user).delete()

        response = self.post()

        self.assertEqual(response.status_code, 302)
        self.assertFalse(RidePost.objects.exists())

    def test_posting_without_a_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(self.url, self.data(self.departure))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(RidePost.objects.exists())

    def test_only_get_and_post(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)


class RideDetailTests(RideTestData):
    def setUp(self):
        self.client.force_login(self.user)

    def url(self, post):
        return reverse("rides:ride_detail", args=[post.pk])

    def test_a_post_whose_departure_has_passed_shows_as_expired(self):
        post = self.make_post(departure=timezone.now() - timedelta(minutes=5))

        response = self.client.get(self.url(post))

        self.assertContains(
            response, '<span class="status status-expired">Expired</span>'
        )
        self.assertNotContains(response, ">Open<")

    def test_another_riders_closed_post_is_404(self):
        # US33 #95 opens open posts to other riders; see test_show_interest.py.
        post = self.make_post(owner=self.other, status=RidePost.CLOSED)
        self.assertEqual(self.client.get(self.url(post)).status_code, 404)

    def test_an_unknown_post_is_404(self):
        response = self.client.get(reverse("rides:ride_detail", args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_guests_are_sent_to_sign_in(self):
        post = self.make_post()
        self.client.logout()

        response = self.client.get(self.url(post))

        self.assertRedirects(
            response, f"{reverse('accounts:signin')}?next={self.url(post)}"
        )

    def test_only_get(self):
        post = self.make_post()
        self.assertEqual(self.client.post(self.url(post)).status_code, 405)

    def test_the_note_is_shown_as_text_never_as_html(self):
        post = self.make_post(note='<script>alert("hi")</script><b>bold</b>')

        response = self.client.get(self.url(post))

        self.assertNotContains(response, "<script>alert")
        self.assertNotContains(response, "<b>bold</b>")
        self.assertContains(
            response, "&lt;script&gt;alert(&quot;hi&quot;)&lt;/script&gt;&lt;b&gt;bold"
        )

    def test_departure_is_shown_in_new_york_time(self):
        post = self.make_post(departure=datetime(2030, 1, 2, 23, 30, tzinfo=NYC_TZ))
        self.assertContains(self.client.get(self.url(post)), "Wed 2 Jan 2030, 11:30 PM")

    def test_one_seat_is_singular(self):
        post = self.make_post(seats=1)
        self.assertContains(self.client.get(self.url(post)), "1 seat offered")


class NoEmailTests(RideTestData):
    """US30 #92: no Epic 4 page ever shows a rider's email address."""

    def test_ride_pages_never_show_an_email_address(self):
        self.client.force_login(self.user)
        post = self.make_post(note="See you there")
        pages = [
            reverse("rides:post_ride") + "?from=161&to=237",
            reverse("rides:ride_detail", args=[post.pk]),
        ]
        for page in pages:
            with self.subTest(page=page):
                html = self.client.get(page).content.decode()
                self.assertNotIn("@", html)
                self.assertNotIn("alex.k", html)


class MapLinkTests(RideTestData):
    def test_trip_summary_has_post_a_shared_ride_for_signed_in_users(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("zones:map"))
        self.assertContains(
            response,
            f'<a id="share-ride-link" href="{reverse("rides:post_ride")}" hidden>'
            "Post a shared ride</a>",
        )
        self.assertContains(response, "rides/js/share-ride-link.js")

    def test_guests_see_sign_in_to_share_a_ride(self):
        response = Client().get(reverse("zones:map"))
        self.assertContains(
            response,
            f'<a id="share-ride-link" href="{reverse("rides:post_ride")}" hidden '
            f'data-signin="{reverse("accounts:signin")}">Sign in to share a ride</a>',
        )
