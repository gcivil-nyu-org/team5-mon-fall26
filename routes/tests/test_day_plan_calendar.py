"""US21 #50 part 2: export a day plan (US20) to a calendar (.ics)."""

from datetime import time
from unittest import mock

from django.urls import reverse

from routes.calendar import build_ics
from routes.planning import day_plan_calendar, day_plan_legs
from routes.tests.test_calendar import NOW, ny, unfold
from routes.tests.test_day_plans import (
    BATTERY_PARK,
    BROOKLYN_HEIGHTS,
    MIDTOWN_CENTER,
    SATURDAY,
    TIMES_SQ,
    DayPlanTestCase,
)

# NOW is Saturday Oct 31 2026, 12:00 EDT. self.plan ("Museum day", Monday):
# Brooklyn Heights 08:00 → Midtown Center 11:15 → Times Sq.


class DayPlanCalendarTestCase(DayPlanTestCase):
    def calendar(self, plan=None, weekly=False):
        plan = plan or self.plan
        stops = list(plan.stops.select_related("zone"))
        return day_plan_calendar(plan, stops, NOW, weekly=weekly)

    def both_legs_with_data(self):
        self.stats(BROOKLYN_HEIGHTS, MIDTOWN_CENTER, 8, fare="22.00", duration=31)
        self.stats(MIDTOWN_CENTER, TIMES_SQ, 11, fare="14.50", duration=12.6)

    def saturday_plan(self, name, times, zones=None):
        return self.make_plan(
            self.user,
            name,
            zones or [BROOKLYN_HEIGHTS, MIDTOWN_CENTER, TIMES_SQ],
            times,
            day=SATURDAY,
        )


class DayPlanCalendarTests(DayPlanCalendarTestCase):
    def test_one_event_per_leg_all_on_the_next_date(self):
        events = self.calendar()["events"]
        self.assertEqual(len(events), 2)
        self.assertEqual(
            [e.start for e in events], [ny(2026, 11, 2, 8, 0), ny(2026, 11, 2, 11, 15)]
        )

    def test_today_when_the_first_leave_time_has_not_passed(self):
        plan = self.saturday_plan("Tonight", [time(18, 0), time(20, 0)])
        self.assertEqual(
            [e.start for e in self.calendar(plan)["events"]],
            [ny(2026, 10, 31, 18, 0), ny(2026, 10, 31, 20, 0)],
        )

    def test_next_week_when_the_first_leave_time_has_passed(self):
        # The second leg (13:00) hasn't passed, but the first (09:00) has.
        plan = self.saturday_plan("Saturday", [time(9, 0), time(13, 0)])
        self.assertEqual(
            [e.start for e in self.calendar(plan)["events"]],
            [ny(2026, 11, 7, 9, 0), ny(2026, 11, 7, 13, 0)],
        )

    def test_a_leave_time_before_the_previous_one_goes_on_the_next_day(self):
        # 22:00 then 00:30: the second trip is after midnight, on Sunday.
        plan = self.saturday_plan("Late", [time(22, 0), time(0, 30)])
        self.assertEqual(
            [e.start for e in self.calendar(plan)["events"]],
            [ny(2026, 10, 31, 22, 0), ny(2026, 11, 1, 0, 30)],
        )

    def test_ends_after_the_typical_duration_rounded_to_the_minute(self):
        self.both_legs_with_data()
        events = self.calendar()["events"]
        self.assertEqual(events[0].end, ny(2026, 11, 2, 8, 31))
        self.assertEqual(events[1].end, ny(2026, 11, 2, 11, 28))  # 12.6 → 13 min

    def test_an_end_can_cross_midnight(self):
        plan = self.saturday_plan("Night", [time(23, 0), time(23, 45)])
        self.stats(MIDTOWN_CENTER, TIMES_SQ, 23, duration=30, day=SATURDAY)
        self.assertEqual(self.calendar(plan)["events"][1].end, ny(2026, 11, 1, 0, 15))

    def test_title_and_description_with_data(self):
        self.both_legs_with_data()
        first = self.calendar()["events"][0]
        self.assertEqual(first.summary, "Taxi: Brooklyn Heights → Midtown Center")
        self.assertEqual(
            first.description.split("\n"),
            [
                "Leave at 08:00",
                "Typical journey time: 31.0 min",
                "Typical fare before tip: $22.00",
                "Trip 1 of 2 in Museum day",
                "Based on past trips (March to May 2026), not a guarantee.",
            ],
        )
        self.assertEqual(first.alarm_minutes, 15)

    def test_no_data_leg_is_a_zero_length_event_at_the_leave_time(self):
        self.stats(BROOKLYN_HEIGHTS, MIDTOWN_CENTER, 8, duration=31)
        calendar = self.calendar()
        second = calendar["events"][1]
        self.assertEqual(second.start, ny(2026, 11, 2, 11, 15))
        self.assertEqual(second.end, second.start)
        self.assertEqual(
            second.summary, "Taxi: Midtown Center → Times Sq/Theatre District"
        )
        self.assertEqual(
            second.description.split("\n"),
            [
                "Not enough past trips to estimate this trip at this hour.",
                "Leave at 11:15",
                "Trip 2 of 2 in Museum day",
                "Based on past trips (March to May 2026), not a guarantee.",
            ],
        )
        self.assertEqual(second.alarm_minutes, 15)
        self.assertEqual(
            calendar["warning"],
            "Some trips have too few past trips for an estimate; "
            "their events show only the leave time.",
        )

    def test_no_warning_when_every_leg_has_data(self):
        self.both_legs_with_data()
        self.assertIsNone(self.calendar()["warning"])

    def test_button_label_uses_the_first_legs_date(self):
        self.assertEqual(
            self.calendar()["button_label"],
            "Add day plan to calendar: Mon, Nov 2, 08:00",
        )

    def test_uids_are_per_plan_and_leg(self):
        self.assertEqual(
            [e.uid for e in self.calendar()["events"]],
            [
                f"dayplan-{self.plan.pk}-leg-1@taxiscope",
                f"dayplan-{self.plan.pk}-leg-2@taxiscope",
            ],
        )

    def test_weekly_repeats_every_event(self):
        events = self.calendar(weekly=True)["events"]
        self.assertTrue(all(e.weekly for e in events))
        text = build_ics(events, NOW)
        self.assertEqual(text.count("RRULE:FREQ=WEEKLY\r\n"), 2)

    def test_legs_are_the_same_as_on_the_page(self):
        self.both_legs_with_data()
        stops = list(self.plan.stops.select_related("zone"))
        self.assertEqual(self.calendar()["legs"], day_plan_legs(self.plan, stops))


class DayPlanCalendarViewTests(DayPlanCalendarTestCase):
    def download(self, plan=None, **params):
        with mock.patch("routes.views.datetime") as fake:
            fake.now.return_value = NOW
            return self.client.get(
                self.url("day_plan_calendar", plan or self.plan), params
            )

    def text(self, response):
        return unfold(response.content.decode("utf-8"))

    def test_content_type_and_filename(self):
        response = self.download()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="day-plan-{self.plan.pk}.ics"',
        )

    def test_file_has_one_event_per_leg_in_new_york_time(self):
        text = self.text(self.download())
        self.assertEqual(text.count("BEGIN:VEVENT"), 2)
        self.assertEqual(text.count("BEGIN:VTIMEZONE"), 1)
        self.assertIn("DTSTART;TZID=America/New_York:20261102T080000\r\n", text)
        self.assertIn("DTSTART;TZID=America/New_York:20261102T111500\r\n", text)
        self.assertIn(f"UID:dayplan-{self.plan.pk}-leg-2@taxiscope\r\n", text)
        self.assertIn("TRIGGER:-PT15M\r\n", text)

    def test_no_email_username_or_attendee(self):
        text = self.text(self.download())
        forbidden = {
            self.user.email,
            self.user.get_username(),
            "alex@example.com",
            "example.com",
            "alex",
            "ORGANIZER",
            "ATTENDEE",
            "MAILTO",
        } - {
            ""
        }  # the test user's email field is empty; its username is the address
        for value in forbidden:
            self.assertNotIn(value, text)

    def test_repeat_weekly_on_every_event(self):
        text = self.text(self.download(repeat="weekly"))
        self.assertEqual(text.count("RRULE:FREQ=WEEKLY\r\n"), 2)

    def test_no_rrule_by_default_or_for_other_values(self):
        self.assertNotIn("RRULE:FREQ=WEEKLY", self.text(self.download()))
        self.assertNotIn("RRULE:FREQ=WEEKLY", self.text(self.download(repeat="yes")))

    def test_four_stops_give_three_events(self):
        plan = self.make_plan(
            self.user,
            "Four stops",
            [BROOKLYN_HEIGHTS, MIDTOWN_CENTER, TIMES_SQ, BATTERY_PARK],
            [time(8, 0), time(9, 0), time(10, 0)],
        )
        self.assertEqual(self.text(self.download(plan)).count("BEGIN:VEVENT"), 3)

    def test_other_users_plan_is_404(self):
        self.client.force_login(self.other)
        self.assertEqual(self.download().status_code, 404)

    def test_missing_plan_is_404(self):
        url = reverse("routes:day_plan_calendar", args=[999999])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        url = self.url("day_plan_calendar", self.plan)
        self.assertRedirects(
            self.client.get(url),
            f"{reverse('accounts:signin')}?next={url}",
            fetch_redirect_response=False,
        )

    def test_post_not_allowed(self):
        url = self.url("day_plan_calendar", self.plan)
        self.assertEqual(self.client.post(url).status_code, 405)


class DayPlanPageCalendarTests(DayPlanCalendarTestCase):
    def page(self, plan=None):
        with mock.patch("routes.views.datetime") as fake:
            fake.now.return_value = NOW
            return self.client.get(self.url("open_day_plan", plan or self.plan))

    def test_button_shows_the_date(self):
        self.both_legs_with_data()
        page = self.page()
        self.assertContains(page, "Add day plan to calendar: Mon, Nov 2, 08:00")
        self.assertNotContains(page, "Some trips have too few past trips")

    def test_warning_when_a_leg_has_no_data(self):
        self.stats(BROOKLYN_HEIGHTS, MIDTOWN_CENTER, 8, duration=31)
        self.assertContains(
            self.page(),
            "⚠ Some trips have too few past trips for an estimate; "
            "their events show only the leave time.",
        )

    def test_form_targets_the_calendar_url_with_get(self):
        page = self.page()
        action = self.url("day_plan_calendar", self.plan)
        self.assertContains(page, f'<form method="get" action="{action}"')
        self.assertContains(
            page,
            '<input type="checkbox" name="repeat" value="weekly"> Repeat every week',
        )

    def test_form_is_under_the_trips(self):
        page = self.page().content.decode()
        self.assertLess(
            page.index('class="day-plan-leg"'),
            page.index(self.url("day_plan_calendar", self.plan)),
        )
