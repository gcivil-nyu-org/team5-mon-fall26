"""US20 #49: multi-stop day plans (Pass A: save, list and view)."""

from datetime import time
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.checks import cascade_errors
from routes.day_plans import create_day_plan, out_of_order_warning
from routes.forms import DayPlanForm
from routes.models import DayPlan, DayPlanStop
from routes.planning import day_plan_legs
from zones.models import RouteHourStats, Zone

MONDAY, SATURDAY = 0, 5
BROOKLYN_HEIGHTS, MIDTOWN_CENTER, TIMES_SQ, BATTERY_PARK = 33, 161, 230, 12


@override_settings(MIN_TRIP_COUNT=5)
class DayPlanTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user("alex@example.com")
        cls.other = User.objects.create_user("other@example.com")
        cls.zones = {
            zone_id: Zone.objects.create(zone_id=zone_id, name=name, borough=borough)
            for zone_id, name, borough in [
                (BROOKLYN_HEIGHTS, "Brooklyn Heights", "Brooklyn"),
                (MIDTOWN_CENTER, "Midtown Center", "Manhattan"),
                (TIMES_SQ, "Times Sq/Theatre District", "Manhattan"),
                (BATTERY_PARK, "Battery Park", "Manhattan"),
            ]
        }
        cls.plan = cls.make_plan(
            cls.user,
            "Museum day",
            [BROOKLYN_HEIGHTS, MIDTOWN_CENTER, TIMES_SQ],
            [time(8, 0), time(11, 15)],
        )

    @classmethod
    def make_plan(cls, user, name, zone_ids, times, day=MONDAY):
        return create_day_plan(user, name, day, [cls.zones[z] for z in zone_ids], times)

    def setUp(self):
        self.client.force_login(self.user)

    def stats(self, pickup, dropoff, hour, fare="20.00", duration=25, day=MONDAY):
        return RouteHourStats.objects.create(
            pickup_zone_id=pickup,
            dropoff_zone_id=dropoff,
            day_of_week=day,
            hour=hour,
            trip_count=10,
            avg_duration_min=duration,
            fare_min=Decimal("10.00"),
            fare_avg=Decimal(fare),
            fare_max=Decimal("40.00"),
        )

    def url(self, name, plan):
        return reverse(f"routes:{name}", args=[plan.pk])


class SaveDayPlanTests(DayPlanTestCase):
    save_url = reverse("routes:save_day_plan")

    def save(self, client=None, **overrides):
        data = {
            "name": "Saturday out",
            "day_of_week": SATURDAY,
            "stops": f"{BROOKLYN_HEIGHTS},{MIDTOWN_CENTER},{TIMES_SQ}",
            "leave_times": "09:00,13:30",
            **overrides,
        }
        return (client or self.client).post(self.save_url, data)

    def errors(self, response):
        self.assertEqual(response.status_code, 400)
        return response.json()["errors"]

    def test_saves_three_stops_in_order(self):
        response = self.save()
        self.assertEqual(response.status_code, 201)
        plan = DayPlan.objects.get(pk=response.json()["id"])
        self.assertEqual(
            (plan.user, plan.name, plan.day_of_week), (self.user, "Saturday out", 5)
        )
        self.assertEqual(
            [(s.position, s.zone_id, s.leave_time) for s in plan.stops.all()],
            [
                (0, BROOKLYN_HEIGHTS, time(9, 0)),
                (1, MIDTOWN_CENTER, time(13, 30)),
                (2, TIMES_SQ, None),
            ],
        )

    def test_response_has_name_and_page_url(self):
        data = self.save().json()
        self.assertEqual(data["name"], "Saturday out")
        self.assertEqual(
            data["url"], reverse("routes:open_day_plan", args=[data["id"]])
        )

    def test_fewer_than_three_stops_is_400(self):
        errors = self.errors(
            self.save(stops=f"{BROOKLYN_HEIGHTS},{TIMES_SQ}", leave_times="09:00")
        )
        self.assertEqual(
            errors["stops"], ["A day plan needs at least 3 stops (2 trips)."]
        )

    def test_more_than_ten_stops_is_400(self):
        errors = self.errors(
            self.save(
                stops=",".join([str(TIMES_SQ)] * 11),
                leave_times=",".join(["09:00"] * 10),
            )
        )
        self.assertEqual(errors["stops"], ["A day plan can have at most 10 stops."])

    def test_ten_stops_is_the_maximum(self):
        response = self.save(
            stops=",".join([str(TIMES_SQ)] * 10), leave_times=",".join(["09:00"] * 9)
        )
        self.assertEqual(response.status_code, 201)

    def test_times_must_match_stops(self):
        errors = self.errors(self.save(leave_times="09:00"))
        self.assertEqual(
            errors["leave_times"], ["Give a leave time for every stop except the last."]
        )
        self.errors(self.save(leave_times="09:00,10:00,11:00"))

    def test_times_must_be_quarter_hours(self):
        errors = self.errors(self.save(leave_times="09:00,13:20"))
        self.assertIn("15-minute steps", errors["leave_times"][0])

    def test_invalid_input_returns_400(self):
        cases = [
            {"stops": "33,abc,230"},
            {"stops": ""},
            {"leave_times": "9am,13:30"},
            {"leave_times": "25:00,13:30"},
            {"leave_times": ""},
            {"day_of_week": 7},
            {"day_of_week": ""},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.errors(self.save(**overrides))
        self.assertEqual(DayPlan.objects.filter(name="Saturday out").count(), 0)

    def test_unknown_zone_is_400(self):
        errors = self.errors(self.save(stops=f"{BROOKLYN_HEIGHTS},999,{TIMES_SQ}"))
        self.assertEqual(errors["stops"], ["Unknown zone: 999."])

    def test_same_zone_leg_allowed(self):
        response = self.save(stops=f"{TIMES_SQ},{TIMES_SQ},{BATTERY_PARK}")
        self.assertEqual(response.status_code, 201)

    def test_name_required_and_max_50(self):
        self.assertIn("name", self.errors(self.save(name="")))
        self.assertIn("name", self.errors(self.save(name="x" * 51)))
        self.assertEqual(self.save(name="x" * 50).status_code, 201)

    def test_names_unique_per_user_others_may_reuse(self):
        errors = self.errors(self.save(name="Museum day"))
        self.assertEqual(
            errors["name"], ["You already have a day plan with this name."]
        )
        self.client.force_login(self.other)
        self.assertEqual(self.save(name="Museum day").status_code, 201)

    def test_concurrent_duplicate_name_gets_message(self):
        # Another request saved "Museum day" after this one was validated.
        with patch("routes.forms.DayPlanForm.clean_name", return_value="Museum day"):
            errors = self.errors(self.save(name="Museum day"))
        self.assertIn("already", errors["name"][0])
        self.assertEqual(DayPlan.objects.filter(user=self.user).count(), 1)
        self.assertEqual(DayPlanStop.objects.count(), 3)  # nothing half-saved

    def test_unrelated_integrity_error_is_reraised(self):
        form = DayPlanForm(
            self.user,
            {
                "name": "New",
                "day_of_week": 1,
                "stops": "33,161,230",
                "leave_times": "09:00,10:00",
            },
        )
        self.assertTrue(form.is_valid())
        error = IntegrityError("foreign key constraint failed")
        with patch.object(DayPlanStop.objects, "bulk_create", side_effect=error):
            with self.assertRaisesRegex(IntegrityError, "foreign key constraint"):
                form.save()

    def test_guest_gets_401(self):
        self.client.logout()
        response = self.save()
        self.assertEqual(response.status_code, 401)
        self.assertFalse(DayPlan.objects.filter(name="Saturday out").exists())

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.save_url).status_code, 405)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.save(client=client).status_code, 403)

    def test_owner_always_comes_from_session(self):
        response = self.save(user=self.other.pk)
        self.assertEqual(DayPlan.objects.get(pk=response.json()["id"]).user, self.user)


class DayPlanModelTests(DayPlanTestCase):
    def test_deleting_user_deletes_day_plans_and_stops(self):
        self.user.delete()
        self.assertFalse(DayPlan.objects.exists())
        self.assertFalse(DayPlanStop.objects.exists())

    def test_cascade_check_passes_for_day_plan_models(self):
        self.assertEqual(cascade_errors([DayPlan, DayPlanStop]), [])

    def test_no_missing_migrations(self):
        call_command(
            "makemigrations", "routes", "--check", "--dry-run", stdout=StringIO()
        )

    def test_position_is_unique_per_plan(self):
        with self.assertRaises(IntegrityError):
            DayPlanStop.objects.create(
                day_plan=self.plan, zone=self.zones[TIMES_SQ], position=1
            )

    def test_str_and_leave_label(self):
        first, *_, last = self.plan.stops.all()
        self.assertEqual(str(self.plan), "Museum day")
        self.assertEqual(str(first), "Museum day #0")
        self.assertEqual((first.leave_label, last.leave_label), ("08:00", ""))

    def test_out_of_order_warning(self):
        stops = list(self.plan.stops.select_related("zone"))
        self.assertIsNone(out_of_order_warning(stops))
        stops[1].leave_time = time(7, 30)
        self.assertEqual(
            out_of_order_warning(stops),
            "Leave times are not in order: Midtown Center (07:30) is before "
            "Brooklyn Heights (08:00).",
        )
        stops[1].leave_time = time(8, 0)
        self.assertIn("is the same as", out_of_order_warning(stops))


class DayPlanLegsTests(DayPlanTestCase):
    def legs(self, plan=None):
        plan = plan or self.plan
        return day_plan_legs(plan, list(plan.stops.select_related("zone")))

    def test_legs_follow_consecutive_stops(self):
        legs = self.legs()
        self.assertEqual(
            [
                (leg["number"], leg["from"].zone_id, leg["to"].zone_id, leg["leave"])
                for leg in legs
            ],
            [
                (1, BROOKLYN_HEIGHTS, MIDTOWN_CENTER, "08:00"),
                (2, MIDTOWN_CENTER, TIMES_SQ, "11:15"),
            ],
        )

    def test_leg_uses_route_stats_for_the_leave_hour(self):
        self.stats(MIDTOWN_CENTER, TIMES_SQ, 11, fare="14.50", duration=12)
        self.stats(MIDTOWN_CENTER, TIMES_SQ, 12, fare="99.00")
        stats = self.legs()[1]["stats"]
        self.assertTrue(stats["enough_data"])
        self.assertEqual(stats["fare_avg"], Decimal("14.50"))
        self.assertEqual(stats["avg_duration_min"], 12)

    def test_leg_windows_match_the_windows_api(self):
        for hour, fare, duration in [
            (6, "15.10", 18),
            (11, "18.00", 30),
            (17, "26.40", 38),
        ]:
            self.stats(BROOKLYN_HEIGHTS, MIDTOWN_CENTER, hour, fare, duration)
        api = self.client.get(
            reverse("zones:route_windows_api"),
            {"from": BROOKLYN_HEIGHTS, "to": MIDTOWN_CENTER, "day": MONDAY},
        ).json()
        windows = self.legs()[0]["windows"]
        self.assertEqual(windows["by_fare"], api["by_fare"])
        self.assertEqual(windows["best"]["fare"]["hour"], api["best"]["fare"]["hour"])
        self.assertEqual(windows["worst"]["duration"]["hour"], 17)

    def test_two_queries_per_leg(self):
        plan = self.plan
        stops = list(plan.stops.select_related("zone"))
        with self.assertNumQueries(2 * (len(stops) - 1)):
            day_plan_legs(plan, stops)


class DayPlanPagesTests(DayPlanTestCase):
    def page(self, plan=None):
        return self.client.get(self.url("open_day_plan", plan or self.plan))

    def test_page_shows_each_legs_fare_duration_best_worst(self):
        self.stats(BROOKLYN_HEIGHTS, MIDTOWN_CENTER, 8, fare="22.00", duration=31)
        self.stats(BROOKLYN_HEIGHTS, MIDTOWN_CENTER, 6, fare="15.10", duration=18)
        self.stats(BROOKLYN_HEIGHTS, MIDTOWN_CENTER, 17, fare="26.40", duration=38)
        self.stats(MIDTOWN_CENTER, TIMES_SQ, 11, fare="14.50", duration=12)
        self.stats(MIDTOWN_CENTER, TIMES_SQ, 9, fare="13.00", duration=10)
        page = self.page()
        self.assertContains(page, "1. Brooklyn Heights → Midtown Center, leave 08:00")
        self.assertContains(page, "$10.00 / $22.00 / $40.00")
        self.assertContains(page, "31.0 min")
        self.assertContains(page, "Cheapest: 06:00–06:59 (avg $15.10)")
        self.assertContains(page, "Fastest: 06:00–06:59 (18.0 min)")
        self.assertContains(page, "Most expensive: 17:00–17:59 (avg $26.40)")
        self.assertContains(page, "Slowest: 17:00–17:59 (38.0 min)")
        self.assertContains(
            page, "2. Midtown Center → Times Sq/Theatre District, leave 11:15"
        )
        self.assertContains(page, "$10.00 / $14.50 / $40.00")
        self.assertNotContains(page, "Not enough data")

    def test_page_label_based_on_past_trips(self):
        self.assertContains(
            self.page(), "Based on past trips (March to May 2026), not a guarantee."
        )

    def test_page_lists_stops_with_leave_times(self):
        page = self.page()
        self.assertContains(page, "Brooklyn Heights (Brooklyn)</span>")
        self.assertContains(page, 'name="leave_time" step="900" value="08:00"')
        self.assertContains(page, 'name="leave_time" step="900" value="11:15"')
        self.assertContains(page, "Times Sq/Theatre District (Manhattan)</span>")
        self.assertContains(page, "Monday: 3 stops, 2 trips")

    def test_leg_without_data_shows_not_enough_data(self):
        page = self.page()
        # Two legs × (fare, duration, best, worst).
        self.assertContains(page, "Not enough data", count=8)

    def test_leg_with_one_qualifying_hour_shows_not_enough_data_for_best_worst(self):
        self.stats(BROOKLYN_HEIGHTS, MIDTOWN_CENTER, 8, fare="22.00")
        page = self.page()
        self.assertContains(page, "$10.00 / $22.00 / $40.00")
        # Leg 1: best and worst; leg 2: everything.
        self.assertContains(page, "Not enough data", count=6)

    def test_mixed_legs_each_labelled_correctly(self):
        self.stats(MIDTOWN_CENTER, TIMES_SQ, 11, fare="14.50", duration=12)
        self.stats(MIDTOWN_CENTER, TIMES_SQ, 9, fare="13.00", duration=10)
        legs = self.page().content.decode().split('class="day-plan-leg"')[1:]
        self.assertEqual(legs[0].count("Not enough data"), 4)
        self.assertEqual(legs[1].count("Not enough data"), 0)

    def test_out_of_order_times_show_a_warning(self):
        plan = self.make_plan(
            self.user,
            "Backwards",
            [BROOKLYN_HEIGHTS, MIDTOWN_CENTER, TIMES_SQ],
            [time(8, 0), time(7, 30)],
        )
        self.assertContains(
            self.page(plan),
            "⚠ Leave times are not in order: Midtown Center (07:30) is before "
            "Brooklyn Heights (08:00).",
        )
        # Only the out-of-order warning: the calendar form can show its own ⚠.
        self.assertNotContains(self.page(), "Leave times are not in order")

    def test_page_query_count(self):
        # Session and user, the plan, its stops, 2 per leg, then the
        # add-stop zone list (Pass B).
        with self.assertNumQueries(2 + 2 + 2 * 2 + 1):
            self.page()

    def test_list_shows_name_day_and_stop_chain(self):
        self.make_plan(
            self.other, "Not mine", [TIMES_SQ, BATTERY_PARK, TIMES_SQ], [time(9, 0)] * 2
        )
        page = self.client.get(reverse("routes:my_day_plans"))
        self.assertContains(page, "Museum day")
        self.assertContains(page, "Monday, 3 stops")
        self.assertContains(
            page, "Brooklyn Heights → Midtown Center → Times Sq/Theatre District"
        )
        self.assertContains(page, self.url("open_day_plan", self.plan))
        self.assertNotContains(page, "Not mine")

    def test_empty_list_explains_how_to_start(self):
        self.client.force_login(self.other)
        self.assertContains(
            self.client.get(reverse("routes:my_day_plans")), "No day plans yet."
        )

    def test_other_users_plan_is_404(self):
        self.client.force_login(self.other)
        self.assertEqual(self.page().status_code, 404)

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        for url in (
            reverse("routes:my_day_plans"),
            self.url("open_day_plan", self.plan),
        ):
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url),
                    f"{reverse('accounts:signin')}?next={url}",
                    fetch_redirect_response=False,
                )

    def test_pages_reject_post(self):
        for url in (
            reverse("routes:my_day_plans"),
            self.url("open_day_plan", self.plan),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 405)


class MapDayPlanTests(DayPlanTestCase):
    def map_page(self):
        return self.client.get(reverse("zones:map")).content.decode()

    def assert_under_selection_rows(self, page, marker):
        # Directly under the Pickup/Dropoff rows, above "Save this route"
        # and the Trip summary.
        self.assertLess(
            page.index('id="dropoff-zone"'), page.index('id="day-plan-panel"')
        )
        self.assertLess(page.index('id="day-plan-panel"'), page.index(marker))
        self.assertLess(page.index(marker), page.index('id="save-route-panel"'))
        self.assertLess(
            page.index('id="save-route-panel"'), page.index('id="summary-panel"')
        )

    def test_map_shows_day_plan_builder_for_signed_in_user(self):
        page = self.map_page()
        self.assertIn('id="day-plan-form"', page)
        self.assertIn(f'action="{reverse("routes:save_day_plan")}"', page)
        self.assertIn('aria-pressed="false" hidden>+ Add stop</button>', page)
        self.assertIn('id="day-plan-day"', page)
        self.assertIn("Save day plan", page)
        self.assertIn("routes/js/day-plan.js", page)
        self.assertNotIn("Sign in to plan a day", page)

    def test_builder_sits_under_pickup_and_dropoff(self):
        page = self.map_page()
        self.assert_under_selection_rows(page, 'id="day-plan-form"')
        self.assertEqual(page.count('id="day-plan-panel"'), 1)  # no old bottom panel

    def test_guest_sees_sign_in_to_plan_a_day_in_the_same_place(self):
        self.client.logout()
        page = self.map_page()
        self.assertIn("Sign in to plan a day", page)
        self.assertNotIn('id="day-plan-form"', page)
        self.assert_under_selection_rows(page, 'id="day-plan-signin"')

    def test_header_links_to_day_plans(self):
        for url in (reverse("zones:map"), reverse("routes:my_plans")):
            with self.subTest(url=url):
                self.assertContains(
                    self.client.get(url),
                    f'<a href="{reverse("routes:my_day_plans")}">Day plans</a>',
                )
