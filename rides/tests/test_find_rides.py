"""US32 #94: Find Shared Rides on My Route."""

from datetime import date, datetime, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from accounts.models import Profile
from rides import search
from rides.forms import RideSearchForm
from rides.models import RidePost
from zones.models import Zone
from zones.views import NYC_TZ

PASSWORD = "a-strong-test-password-32"
# Wednesday 11 Nov 2026, 08:00 in New York. Every test runs at this moment.
NOW = datetime(2026, 11, 11, 8, 0, tzinfo=NYC_TZ)
TODAY = NOW.date()
TOMORROW = TODAY + timedelta(days=1)
# Midtown Center (161) is next to Midtown East (162); JFK (132) is next to
# Jamaica Bay (2). Upper East Side South (237) is next to neither.
NEIGHBORS = {161: [162], 162: [161], 132: [2], 2: [132], 237: []}


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), NYC_TZ)


class FindRidesTestData(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.rider = users.create_user("alex.k@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.rider, display_name="Night Owl")
        cls.owner = users.create_user("sam.owner@example.com", password=PASSWORD)
        Profile.objects.create(user=cls.owner, display_name="Early Bird")
        zone = Zone.objects.create
        cls.midtown = zone(zone_id=161, name="Midtown Center", borough="Manhattan")
        cls.midtown_east = zone(zone_id=162, name="Midtown East", borough="Manhattan")
        cls.jfk = zone(zone_id=132, name="JFK Airport", borough="Queens")
        cls.jamaica_bay = zone(zone_id=2, name="Jamaica Bay", borough="Queens")
        cls.ues = zone(zone_id=237, name="Upper East Side South", borough="Manhattan")

    def setUp(self):
        for target in (
            mock.patch("rides.search.load_zone_neighbors", return_value=NEIGHBORS),
            mock.patch("django.utils.timezone.now", return_value=NOW),
        ):
            target.start()
            self.addCleanup(target.stop)

    def post(self, pickup=None, dropoff=None, departure=None, owner=None, **fields):
        return RidePost.objects.create(
            owner=owner or self.owner,
            pickup_zone=pickup or self.midtown,
            dropoff_zone=dropoff or self.jfk,
            departure_at=departure or at(TOMORROW, 9),
            seats=fields.pop("seats", 2),
            **fields,
        )

    def find(self, day=TOMORROW, at_time=None, pickup=None, dropoff=None):
        return search.find_rides(
            self.rider,
            pickup or self.midtown,
            dropoff or self.jfk,
            day,
            at_time,
            now=NOW,
        )

    def query(self, **params):
        params.setdefault("from", self.midtown.pk)
        params.setdefault("to", self.jfk.pk)
        params.setdefault("date", TOMORROW.isoformat())
        return f"{reverse('rides:find_rides')}?{urlencode(params)}"


class MatchingTests(FindRidesTestData):
    def test_same_route_and_adjacent_zones_match_exact_first(self):
        nearby_pickup = self.post(pickup=self.midtown_east, departure=at(TOMORROW, 7))
        nearby_both = self.post(
            pickup=self.midtown_east,
            dropoff=self.jamaica_bay,
            departure=at(TOMORROW, 6),
        )
        exact_late = self.post(departure=at(TOMORROW, 20))
        nearby_dropoff = self.post(dropoff=self.jamaica_bay, departure=at(TOMORROW, 8))
        exact_early = self.post(departure=at(TOMORROW, 10))

        results = self.find()

        self.assertEqual(
            [match.post for match in results],
            [exact_early, exact_late, nearby_both, nearby_pickup, nearby_dropoff],
        )
        self.assertEqual(
            [match.label for match in results],
            [
                "Same route",
                "Same route",
                "Nearby pickup and dropoff",
                "Nearby pickup",
                "Nearby dropoff",
            ],
        )
        self.assertTrue(results[0].exact)
        self.assertFalse(results[2].exact)

    def test_zones_that_are_not_adjacent_do_not_match(self):
        self.post(pickup=self.ues)
        self.post(dropoff=self.ues)
        self.assertEqual(self.find(), [])

    def test_the_route_is_one_way(self):
        self.post(pickup=self.jfk, dropoff=self.midtown)
        self.assertEqual(self.find(), [])

    def test_only_posts_departing_on_the_chosen_date_match(self):
        on_the_day = [
            self.post(departure=at(TOMORROW, 0)),
            self.post(departure=at(TOMORROW, 23, 45)),
        ]
        self.post(departure=at(TOMORROW + timedelta(days=1), 0))
        self.post(departure=at(TODAY, 23, 45))
        self.assertEqual([match.post for match in self.find()], on_the_day)

    def test_with_a_time_only_posts_within_1_hour_of_it_match(self):
        inside = [
            self.post(departure=at(TOMORROW, 8)),
            self.post(departure=at(TOMORROW, 9, 15)),
            self.post(departure=at(TOMORROW, 10)),
        ]
        self.post(departure=at(TOMORROW, 7, 45))
        self.post(departure=at(TOMORROW, 10, 15))
        results = self.find(at_time=time(9, 0))
        self.assertEqual([match.post for match in results], inside)

    def test_the_hour_window_stays_within_the_chosen_date(self):
        just_after_midnight = self.post(departure=at(TOMORROW, 0, 30))
        self.post(departure=at(TODAY, 23, 45))
        results = self.find(at_time=time(0, 15))
        self.assertEqual([match.post for match in results], [just_after_midnight])

    def test_full_closed_expired_and_own_posts_are_not_listed(self):
        listed = self.post()
        self.post(status=RidePost.FULL)
        self.post(status=RidePost.CLOSED)
        self.post(owner=self.rider)
        expired = self.post(departure=at(TODAY, 7, 45))
        self.assertTrue(expired.is_expired(NOW))
        self.assertEqual([m.post for m in self.find()], [listed])
        self.assertEqual(self.find(day=TODAY), [])

    def test_zones_without_neighbors_still_match_the_same_route(self):
        exact = self.post(pickup=self.ues)
        results = self.find(pickup=self.ues)
        self.assertEqual([match.post for match in results], [exact])

    def test_a_zone_missing_from_the_neighbors_file_only_matches_itself(self):
        exact = self.post(pickup=self.jamaica_bay, dropoff=self.ues)
        with mock.patch("rides.search.load_zone_neighbors", return_value={}):
            results = self.find(pickup=self.jamaica_bay, dropoff=self.ues)
        self.assertEqual([match.post for match in results], [exact])

    def test_each_match_has_the_display_name_and_seats_left(self):
        self.post(seats=3, note="Flight at 11")
        match = self.find()[0]
        self.assertEqual(match.owner_name, "Early Bird")
        self.assertEqual(match.post.seats_left(), 3)


class FormTests(FindRidesTestData):
    def form(self, **overrides):
        data = {
            "from": self.midtown.pk,
            "to": self.jfk.pk,
            "date": TOMORROW.isoformat(),
            "time": "",
        }
        data.update(overrides)
        return RideSearchForm(data, now=NOW)

    def test_route_and_date_are_required_and_time_is_optional(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["time"])
        self.assertEqual(form.cleaned_data["from"], self.midtown)
        self.assertEqual(form.cleaned_data["to"], self.jfk)

        form = self.form(**{"from": "", "to": "", "date": ""})
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors,
            {
                "from": ["Choose a pickup zone."],
                "to": ["Choose a dropoff zone."],
                "date": ["Choose a date."],
            },
        )

    def test_a_time_is_kept(self):
        form = self.form(time="09:30")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["time"], time(9, 30))

    def test_the_same_zone_twice_is_rejected(self):
        form = self.form(to=self.midtown.pk)
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["to"],
            ["Choose a dropoff zone that is different from the pickup zone."],
        )

    def test_a_date_in_the_past_or_more_than_14_days_ahead_is_rejected(self):
        self.assertTrue(self.form(date=TODAY.isoformat()).is_valid())
        last = TODAY + timedelta(days=14)
        self.assertTrue(self.form(date=last.isoformat()).is_valid())
        for day, message in (
            (TODAY - timedelta(days=1), "Choose today or a later date."),
            (last + timedelta(days=1), "Choose a date in the next 14 days."),
        ):
            form = self.form(date=day.isoformat())
            self.assertFalse(form.is_valid())
            self.assertEqual(form.errors["date"], [message])

    def test_the_date_box_offers_today_to_14_days_ahead(self):
        widget = self.form().fields["date"].widget
        self.assertEqual(widget.input_type, "date")
        self.assertEqual(widget.attrs["min"], TODAY.isoformat())
        self.assertEqual(widget.attrs["max"], (TODAY + timedelta(days=14)).isoformat())

    def test_zones_come_from_the_map(self):
        Zone.objects.create(zone_id=264, name="Unknown", borough="Unknown")
        form = self.form(**{"from": 264})
        self.assertFalse(form.is_valid())
        self.assertIn("from", form.errors)

    def test_date_for_day_gives_the_next_date_on_that_weekday(self):
        # NOW is a Wednesday (2) in New York.
        self.assertEqual(NOW.weekday(), 2)
        self.assertEqual(search.date_for_day("2", NOW), TODAY)
        self.assertEqual(search.date_for_day("3", NOW), TOMORROW)
        self.assertEqual(search.date_for_day("1", NOW), TODAY + timedelta(days=6))
        for bad in (None, "", "7", "-1", "monday"):
            self.assertIsNone(search.date_for_day(bad, NOW))


class PageTests(FindRidesTestData):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.rider)

    def test_searching_a_route_lists_matching_posts_with_their_details(self):
        self.post(seats=3, note="Flight at 11, <b>one bag</b>")
        self.post(pickup=self.midtown_east, departure=at(TOMORROW, 7))
        response = self.client.get(self.query())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "rides/find_rides.html")
        self.assertContains(response, "2 shared rides found")
        content = response.content.decode()
        self.assertLess(content.index("Same route"), content.index("Nearby pickup"))
        self.assertContains(response, "Early Bird")
        self.assertContains(response, "Midtown Center (Manhattan)")
        self.assertContains(response, "JFK Airport (Queens)")
        self.assertContains(response, "Thu 12 Nov 2026, 9:00 AM")
        self.assertContains(response, "3 seats left")
        self.assertContains(response, "Flight at 11, &lt;b&gt;one bag&lt;/b&gt;")

    def test_one_seat_left_is_singular(self):
        self.post(seats=1)
        response = self.client.get(self.query())
        self.assertContains(response, "1 shared ride found")
        self.assertContains(response, "1 seat left")

    def test_a_time_filters_the_list(self):
        self.post(departure=at(TOMORROW, 9))
        self.post(departure=at(TOMORROW, 18))
        response = self.client.get(self.query(time="17:30"))
        self.assertContains(response, "1 shared ride found")
        self.assertContains(response, "6:00 PM")
        self.assertNotContains(response, "9:00 AM")

    def test_posts_never_show_an_email_address(self):
        self.post(note="See you there")
        response = self.client.get(self.query())
        self.assertNotContains(response, "@")
        self.assertNotContains(response, "sam.owner")

    def test_no_matches_offers_to_post_the_same_route_and_date(self):
        response = self.client.get(self.query(time="09:30"))
        self.assertContains(response, "No shared rides match this route and date yet.")
        post_link = (
            reverse("rides:post_ride")
            + "?"
            + urlencode(
                {
                    "from": self.midtown.pk,
                    "to": self.jfk.pk,
                    "date": TOMORROW.isoformat(),
                    "time": "09:30",
                }
            )
        )
        self.assertContains(response, f'href="{post_link.replace("&", "&amp;")}"')
        self.assertContains(response, "Post a shared ride")

    def test_no_matches_without_a_time_leaves_it_out_of_the_post_link(self):
        response = self.client.get(self.query())
        post_link = (
            reverse("rides:post_ride")
            + "?"
            + urlencode(
                {
                    "from": self.midtown.pk,
                    "to": self.jfk.pk,
                    "date": TOMORROW.isoformat(),
                }
            )
        )
        self.assertContains(response, f'href="{post_link.replace("&", "&amp;")}"')

    def test_the_empty_page_shows_the_form_and_no_results(self):
        response = self.client.get(reverse("rides:find_rides"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<form method="get"')
        self.assertNotContains(response, "shared rides found")
        self.assertNotContains(response, "No shared rides match")

    def test_from_the_trip_summary_the_day_becomes_the_next_date_and_searches(self):
        self.post()
        params = {"from": self.midtown.pk, "to": self.jfk.pk, "day": 3}
        response = self.client.get(f"{reverse('rides:find_rides')}?{urlencode(params)}")
        self.assertContains(response, f'value="{TOMORROW.isoformat()}"')
        self.assertContains(response, "1 shared ride found")

    def test_zones_without_a_date_fill_in_the_form_without_searching(self):
        params = {"from": self.midtown.pk, "to": self.jfk.pk}
        response = self.client.get(f"{reverse('rides:find_rides')}?{urlencode(params)}")
        self.assertContains(response, f'<option value="{self.midtown.pk}" selected>')
        self.assertContains(response, f'value="{TODAY.isoformat()}"')
        self.assertNotContains(response, "shared rides found")

    def test_an_invalid_search_shows_the_reason_and_no_results(self):
        self.post()
        response = self.client.get(self.query(to=self.midtown.pk))
        self.assertContains(
            response, "Choose a dropoff zone that is different from the pickup zone."
        )
        self.assertNotContains(response, "shared ride found")

    def test_only_get_is_allowed(self):
        response = self.client.post(self.query())
        self.assertEqual(response.status_code, 405)


class AccessTests(FindRidesTestData):
    def test_guests_see_a_sign_in_prompt_in_place_of_the_list(self):
        self.post()
        response = Client().get(self.query())
        self.assertEqual(response.status_code, 200)
        signin = f"{reverse('accounts:signin')}?{urlencode({'next': self.query()})}"
        self.assertContains(
            response,
            f'<a id="find-ride-signin" href="{signin.replace("&", "&amp;")}">'
            "Sign in to find a shared ride</a>",
        )
        self.assertNotContains(response, "Early Bird")
        self.assertNotContains(response, "<form")

    def test_a_rider_without_a_display_name_chooses_one_first(self):
        no_name = get_user_model().objects.create_user(
            "no.name@example.com", password=PASSWORD
        )
        self.client.force_login(no_name)
        response = self.client.get(self.query())
        expected = (
            f"{reverse('accounts:display_name')}?{urlencode({'next': self.query()})}"
        )
        self.assertRedirects(response, expected, fetch_redirect_response=False)


class PostLinkPrefillTests(FindRidesTestData):
    """The "Post a shared ride" link from an empty search fills in the date
    and time on the US31 form."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.rider)

    def departure_value(self, **params):
        url = f"{reverse('rides:post_ride')}?{urlencode(params)}"
        response = self.client.get(url)
        return response.context["form"].initial["departure_at"]

    def test_date_and_time_are_used(self):
        self.assertEqual(
            self.departure_value(date=TOMORROW.isoformat(), time="09:30"),
            at(TOMORROW, 9, 30),
        )

    def test_a_time_off_the_quarter_hour_is_rounded_up(self):
        self.assertEqual(
            self.departure_value(date=TOMORROW.isoformat(), time="09:20"),
            at(TOMORROW, 9, 30),
        )

    def test_a_date_alone_keeps_the_usual_time_of_day(self):
        # The usual start is the first quarter hour at least 15 minutes away.
        self.assertEqual(
            self.departure_value(date=TOMORROW.isoformat()), at(TOMORROW, 8, 15)
        )

    def test_a_past_too_far_or_bad_value_falls_back_to_the_usual_start(self):
        usual = at(TODAY, 8, 15)
        for params in (
            {"date": TODAY.isoformat(), "time": "07:00"},
            {"date": (TODAY + timedelta(days=15)).isoformat()},
            {"date": "tomorrow"},
            {"date": TOMORROW.isoformat(), "time": "25:00"},
            {},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.departure_value(**params), usual)


class MapLinkTests(FindRidesTestData):
    def test_trip_summary_has_find_a_shared_ride_for_signed_in_users(self):
        self.client.force_login(self.rider)
        response = self.client.get(reverse("zones:map"))
        self.assertContains(
            response,
            f'<a id="find-ride-link" href="{reverse("rides:find_rides")}" hidden>'
            "Find a shared ride</a>",
        )
        self.assertContains(response, "rides/js/find-ride-link.js")
        content = response.content.decode()
        self.assertLess(
            content.index('id="report-fare-link"'), content.index('id="find-ride-link"')
        )

    def test_guests_see_sign_in_to_find_a_shared_ride(self):
        response = Client().get(reverse("zones:map"))
        self.assertContains(
            response,
            f'<a id="find-ride-link" href="{reverse("rides:find_rides")}" hidden '
            f'data-signin="{reverse("accounts:signin")}">'
            "Sign in to find a shared ride</a>",
        )

    def test_the_nav_links_to_find_a_shared_ride(self):
        self.client.force_login(self.rider)
        response = self.client.get(reverse("reports:my_reports"))
        self.assertContains(
            response, f'<a href="{reverse("rides:find_rides")}">Shared rides</a>'
        )


class SeatsLeftTests(FindRidesTestData):
    def test_seats_left_is_the_seats_offered_until_riders_are_accepted(self):
        self.assertEqual(self.post(seats=2).seats_left(), 2)


class DateEdgeTests(FindRidesTestData):
    def test_find_rides_uses_now_by_default(self):
        self.post()
        results = search.find_rides(self.rider, self.midtown, self.jfk, TOMORROW)
        self.assertEqual(len(results), 1)

    def test_form_uses_now_by_default(self):
        form = RideSearchForm(
            {"from": self.midtown.pk, "to": self.jfk.pk, "date": TODAY.isoformat()}
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(timezone.now(), NOW)
        self.assertIsInstance(form.cleaned_data["date"], date)
