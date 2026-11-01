"""US21 #50: export a plan to a calendar (.ics)."""

from datetime import datetime, time, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from routes.calendar import (
    CalendarEvent,
    build_ics,
    escape_text,
    fold_line,
    next_occurrence,
)
from routes.models import TripPlan
from routes.planning import plan_calendar
from routes.tests.test_trip_plans import TripPlanTestCase
from zones.views import NYC_TZ

MONDAY, TUESDAY, FRIDAY, SATURDAY, SUNDAY = 0, 1, 4, 5, 6

# Saturday Oct 31 2026, 12:00 EDT. Clocks go back on Sunday Nov 1 at 02:00.
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=NYC_TZ)


def ny(*args, fold=0):
    return datetime(*args, tzinfo=NYC_TZ, fold=fold)


def unfold(text):
    return text.replace("\r\n ", "")


def event(**overrides):
    fields = {
        "uid": "tripplan-7@taxiscope",
        "start": ny(2026, 11, 6, 8, 45),
        "end": ny(2026, 11, 6, 9, 30),
        "summary": "Taxi: Midtown Center → JFK Airport",
        "description": "Leave by Friday 08:45\nPlan: Friday flight",
        **overrides,
    }
    return CalendarEvent(**fields)


class NextOccurrenceTests(SimpleTestCase):
    def test_today_not_yet_passed_is_today(self):
        self.assertEqual(next_occurrence(SATURDAY, 18, 0, NOW), ny(2026, 10, 31, 18, 0))

    def test_today_already_passed_goes_to_next_week(self):
        self.assertEqual(next_occurrence(SATURDAY, 9, 0, NOW), ny(2026, 11, 7, 9, 0))

    def test_start_equal_to_now_is_today(self):
        self.assertEqual(next_occurrence(SATURDAY, 12, 0, NOW), NOW)

    def test_later_day_this_week(self):
        self.assertEqual(next_occurrence(MONDAY, 9, 0, NOW), ny(2026, 11, 2, 9, 0))

    def test_uses_new_york_date_not_server_utc(self):
        # Friday 22:00 in New York is already Saturday 02:00 in UTC.
        now = ny(2026, 10, 30, 22, 0).astimezone(timezone.utc)
        self.assertEqual(next_occurrence(FRIDAY, 23, 0, now), ny(2026, 10, 30, 23, 0))

    def test_dst_week_keeps_wall_clock_time(self):
        start = next_occurrence(MONDAY, 9, 0, NOW)
        self.assertEqual((start.hour, start.minute), (9, 0))
        self.assertEqual(start.utcoffset(), timedelta(hours=-5))
        self.assertEqual(NOW.utcoffset(), timedelta(hours=-4))

    def test_ambiguous_time_on_nov_1_uses_first_occurrence(self):
        start = next_occurrence(SUNDAY, 1, 30, NOW)
        self.assertEqual(start.date().isoformat(), "2026-11-01")
        self.assertEqual(start.utcoffset(), timedelta(hours=-4))  # EDT

    def test_first_ambiguous_time_already_passed_goes_to_next_week(self):
        # 01:20 EST happens after 01:30 EDT on the same night.
        now = ny(2026, 11, 1, 1, 20, fold=1)
        start = next_occurrence(SUNDAY, 1, 30, now)
        self.assertEqual(start, ny(2026, 11, 8, 1, 30))

    def test_spring_gap_time_does_not_fail(self):
        start = next_occurrence(SUNDAY, 2, 30, ny(2027, 3, 13, 12, 0))
        self.assertEqual(
            (start.date().isoformat(), start.hour, start.minute), ("2027-03-14", 2, 30)
        )
        self.assertIn(
            "DTSTART;TZID=America/New_York:20270314T023000",
            build_ics([event(start=start, end=start)], NOW),
        )


class IcsFormatTests(SimpleTestCase):
    def test_crlf_line_endings(self):
        text = build_ics([event()], NOW)
        self.assertTrue(text.endswith("END:VCALENDAR\r\n"))
        self.assertEqual(text.count("\n"), text.count("\r\n"))

    def test_lines_at_most_75_octets(self):
        long = event(description="A long description, " * 20)
        for line in build_ics([long], NOW).encode("utf-8").split(b"\r\n"):
            self.assertLessEqual(len(line), 75)

    def test_folding_never_splits_utf8(self):
        # Shift the arrows so a fold lands at every byte offset of "→".
        for padding in range(3):
            summary = "x" * padding + "Taxi: " + "→" * 60
            text = build_ics([event(summary=summary)], NOW)
            for line in text.encode("utf-8").split(b"\r\n"):
                self.assertLessEqual(len(line), 75)
                line.decode("utf-8")  # raises if a character was split
            self.assertIn(f"SUMMARY:{summary}\r\n", unfold(text))

    def test_fold_line(self):
        self.assertEqual(fold_line("SUMMARY:short"), "SUMMARY:short")
        folded = fold_line("D:" + "a" * 100).split("\r\n")
        self.assertEqual([len(part) for part in folded], [75, 28])
        self.assertTrue(folded[1].startswith(" "))

    def test_escapes_backslash_semicolon_comma_newline(self):
        self.assertEqual(escape_text("a\\b;c,d\ne"), "a\\\\b\\;c\\,d\\ne")
        text = unfold(build_ics([event(summary="Home; office, gym\\x")], NOW))
        self.assertIn("SUMMARY:Home\\; office\\, gym\\\\x\r\n", text)
        self.assertIn(
            "DESCRIPTION:Leave by Friday 08:45\\nPlan: Friday flight\r\n", text
        )

    def test_header_has_version_prodid_calscale(self):
        text = build_ics([event()], NOW)
        self.assertTrue(
            text.startswith(
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                "PRODID:-//TaxiScope NYC//Trip plans//EN\r\n"
                "CALSCALE:GREGORIAN\r\nMETHOD:PUBLISH\r\n"
            )
        )

    def test_dtstart_dtend_use_tzid_and_vtimezone_present(self):
        text = build_ics([event()], NOW)
        self.assertIn("DTSTART;TZID=America/New_York:20261106T084500\r\n", text)
        self.assertIn("DTEND;TZID=America/New_York:20261106T093000\r\n", text)
        self.assertIn("BEGIN:VTIMEZONE\r\nTZID:America/New_York\r\n", text)

    def test_vtimezone_matches_zoneinfo_2026_to_2030(self):
        text = build_ics([event()], NOW)
        self.assertIn("RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", text)
        self.assertIn("RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", text)

        def nth_sunday(year, month, n):
            first = datetime(year, month, 1)
            return 1 + (6 - first.weekday()) % 7 + 7 * (n - 1)

        def offset_hours(*args):
            return ny(*args).utcoffset().total_seconds() / 3600

        for year in range(2026, 2031):
            with self.subTest(year=year):
                spring = nth_sunday(year, 3, 2)
                autumn = nth_sunday(year, 11, 1)
                self.assertEqual(offset_hours(year, 3, spring, 1, 59), -5)
                self.assertEqual(offset_hours(year, 3, spring, 3, 0), -4)
                self.assertEqual(offset_hours(year, 11, autumn, 0, 59), -4)
                self.assertEqual(offset_hours(year, 11, autumn, 3, 0), -5)

    def test_dtstamp_is_utc(self):
        self.assertIn("DTSTAMP:20261031T160000Z\r\n", build_ics([event()], NOW))

    def test_alarm_before_the_start(self):
        self.assertIn("TRIGGER:-PT15M\r\n", build_ics([event()], NOW))
        self.assertIn("TRIGGER:-PT1H\r\n", build_ics([event(alarm_minutes=60)], NOW))

    def test_rrule_only_when_weekly(self):
        self.assertNotIn("RRULE:FREQ=WEEKLY", build_ics([event()], NOW))
        self.assertIn("RRULE:FREQ=WEEKLY\r\n", build_ics([event(weekly=True)], NOW))

    def test_several_events_share_one_vtimezone(self):
        text = build_ics([event(), event(uid="other@taxiscope")], NOW)
        self.assertEqual(text.count("BEGIN:VEVENT"), 2)
        self.assertEqual(text.count("BEGIN:VTIMEZONE"), 1)


class PlanCalendarTests(TripPlanTestCase):
    """Office (1) → Home (2). arrive_plan: Monday 09:15. cheapest_plan:
    Friday 22:37 ("Friday night")."""

    def calendar(self, plan, weekly=False):
        return plan_calendar(plan, NOW, weekly=weekly)

    def arrive_stats(self):
        # Same numbers as the US17 page test: leave Monday 08:30.
        self.stats(MONDAY, 9, "20.00", duration=20)
        self.stats(MONDAY, 8, "12.34", duration=35)

    def test_arrive_by_starts_at_leave_and_ends_at_arrival(self):
        self.arrive_stats()
        event = self.calendar(self.arrive_plan)["event"]
        self.assertEqual(event.start, ny(2026, 11, 2, 8, 30))
        self.assertEqual(event.end, ny(2026, 11, 2, 9, 15))
        self.assertEqual(event.alarm_minutes, 15)

    def test_title_includes_route(self):
        self.arrive_stats()
        self.assertEqual(
            self.calendar(self.arrive_plan)["event"].summary, "Taxi: Office → Home"
        )

    def test_description_has_leave_arrival_duration_fare_plan_name_disclaimer(self):
        self.arrive_stats()
        self.assertEqual(
            self.calendar(self.arrive_plan)["event"].description.split("\n"),
            [
                "Leave by Monday 08:30",
                "Arrive by Monday 09:15",
                "Typical journey time: 35.0 min",
                "Typical fare before tip: $12.34",
                "Plan: Monday arrival",
                "Based on past trips (March to May 2026), not a guarantee.",
            ],
        )

    def test_leave_on_previous_day(self):
        plan = TripPlan.objects.create(
            user=self.user,
            name="Late arrival",
            pickup_zone=self.pickup,
            dropoff_zone=self.dropoff,
            mode=TripPlan.ARRIVE_BY,
            day_of_week=TUESDAY,
            time=time(0, 30),
        )
        self.stats(TUESDAY, 0, "18.00", duration=45)
        self.stats(MONDAY, 23, "19.00", duration=45)
        calendar = self.calendar(plan)
        self.assertEqual(calendar["event"].start, ny(2026, 11, 2, 23, 45))
        self.assertEqual(calendar["event"].end, ny(2026, 11, 3, 0, 30))
        self.assertEqual(calendar["button_label"], "Add to calendar: Mon, Nov 2, 23:45")

    def test_cheapest_crosses_midnight(self):
        self.stats(FRIDAY, 22, "30.00")
        self.stats(SATURDAY, 0, "21.00", duration=40)
        calendar = self.calendar(self.cheapest_plan)
        event = calendar["event"]
        self.assertEqual(event.start, ny(2026, 11, 7, 0, 0))
        self.assertEqual(event.end, ny(2026, 11, 7, 0, 40))
        self.assertEqual(event.summary, "Taxi: Office → Home")
        self.assertEqual(
            event.description.split("\n")[:4],
            [
                "Leave at Saturday 00:00 (cheapest of the 3 hours from Friday 22:37)",
                "Expected arrival: Saturday 00:40",
                "Typical journey time: 40.0 min",
                "Typical fare before tip: $21.00",
            ],
        )
        self.assertIsNone(calendar["warning"])

    def test_page_label_and_file_use_the_same_date(self):
        self.arrive_stats()
        calendar = self.calendar(self.arrive_plan)
        self.assertEqual(calendar["button_label"], "Add to calendar: Mon, Nov 2, 08:30")
        self.assertIn(
            "DTSTART;TZID=America/New_York:20261102T083000",
            build_ics([calendar["event"]], NOW),
        )

    def test_file_follows_new_statistics(self):
        self.stats(MONDAY, 9, "20.00", duration=20)
        departure_hour = self.stats(MONDAY, 8, "12.34", duration=35)
        before = self.calendar(self.arrive_plan)["event"]
        departure_hour.avg_duration_min = 50
        departure_hour.save()
        after = self.calendar(self.arrive_plan)["event"]
        self.assertEqual(before.start, ny(2026, 11, 2, 8, 30))
        self.assertEqual(after.start, ny(2026, 11, 2, 8, 15))

    def test_arrive_by_no_data_event(self):
        calendar = self.calendar(self.arrive_plan)
        event = calendar["event"]
        self.assertEqual(event.start, ny(2026, 11, 2, 9, 15))
        self.assertEqual(event.end, event.start)
        self.assertEqual(event.summary, "Arrive at Home by 09:15 (from Office)")
        self.assertEqual(event.alarm_minutes, 60)
        self.assertEqual(
            event.description.split("\n")[0],
            "Not enough past trips to estimate when to leave for this route "
            "at this hour.",
        )
        self.assertNotIn("Leave", event.description)
        self.assertEqual(
            calendar["button_label"], "Add arrival time to calendar: Mon, Nov 2, 09:15"
        )
        self.assertTrue(
            calendar["warning"].endswith(
                "The calendar event will only show your arrival time."
            )
        )

    def test_cheapest_no_data_event(self):
        calendar = self.calendar(self.cheapest_plan)
        event = calendar["event"]
        self.assertEqual(event.start, ny(2026, 11, 6, 22, 37))
        self.assertEqual(event.end, event.start)
        self.assertEqual(event.summary, "Taxi: Office → Home (from 22:37)")
        self.assertEqual(event.alarm_minutes, 15)
        self.assertEqual(
            event.description.split("\n")[0],
            "Not enough past trips to find the cheapest hour for this route.",
        )
        self.assertNotIn("Leave", event.description)
        self.assertEqual(
            calendar["button_label"], "Add start time to calendar: Fri, Nov 6, 22:37"
        )
        self.assertTrue(
            calendar["warning"].endswith(
                "The calendar event will only show your start time."
            )
        )

    def test_uid_is_tripplan_id_at_taxiscope(self):
        self.assertEqual(
            self.calendar(self.arrive_plan)["event"].uid,
            f"tripplan-{self.arrive_plan.pk}@taxiscope",
        )


class CalendarViewTests(TripPlanTestCase):
    def download(self, plan, **params):
        with mock.patch("routes.views.datetime") as fake:
            fake.now.return_value = NOW
            return self.client.get(self.url("plan_calendar", plan), params)

    def test_content_type_is_text_calendar_utf8(self):
        response = self.download(self.arrive_plan)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        self.assertIn("BEGIN:VEVENT", response.content.decode("utf-8"))

    def test_filename_has_no_plan_name(self):
        response = self.download(self.arrive_plan)
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="plan-{self.arrive_plan.pk}.ics"',
        )

    def test_no_email_username_or_attendee(self):
        text = unfold(self.download(self.arrive_plan).content.decode("utf-8"))
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
        self.assertIn(f"UID:tripplan-{self.arrive_plan.pk}@taxiscope\r\n", text)

    def test_file_and_page_agree(self):
        text = self.download(self.cheapest_plan).content.decode("utf-8")
        self.assertIn("DTSTART;TZID=America/New_York:20261106T223700", text)
        with mock.patch("routes.views.datetime") as fake:
            fake.now.return_value = NOW
            page = self.client.get(self.url("open_plan", self.cheapest_plan))
        self.assertContains(page, "Add start time to calendar: Fri, Nov 6, 22:37")

    def test_repeat_weekly_adds_rrule(self):
        text = self.download(self.arrive_plan, repeat="weekly").content.decode()
        self.assertIn("RRULE:FREQ=WEEKLY\r\n", text)

    def test_no_rrule_by_default(self):
        text = self.download(self.arrive_plan).content.decode()
        self.assertNotIn("RRULE:FREQ=WEEKLY", text)

    def test_other_repeat_value_means_no_rrule(self):
        text = self.download(self.arrive_plan, repeat="yes").content.decode()
        self.assertNotIn("RRULE:FREQ=WEEKLY", text)

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        url = self.url("plan_calendar", self.arrive_plan)
        self.assertRedirects(
            self.client.get(url),
            f"{reverse('accounts:signin')}?next={url}",
            fetch_redirect_response=False,
        )

    def test_other_users_plan_is_404(self):
        self.assertEqual(self.download(self.secret).status_code, 404)

    def test_missing_plan_is_404(self):
        url = reverse("routes:plan_calendar", args=[999999])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_post_not_allowed(self):
        url = self.url("plan_calendar", self.arrive_plan)
        self.assertEqual(self.client.post(url).status_code, 405)


class PlanPageCalendarTests(TripPlanTestCase):
    def page(self, plan):
        with mock.patch("routes.views.datetime") as fake:
            fake.now.return_value = NOW
            return self.client.get(self.url("open_plan", plan))

    def test_button_shows_date(self):
        self.stats(MONDAY, 9, "20.00", duration=20)
        self.stats(MONDAY, 8, "12.34", duration=35)
        page = self.page(self.arrive_plan)
        self.assertContains(page, "Add to calendar: Mon, Nov 2, 08:30")
        self.assertNotContains(page, "⚠")

    def test_no_data_shows_warning_and_arrival_label(self):
        page = self.page(self.arrive_plan)
        self.assertContains(
            page,
            "⚠ Not enough past trips to estimate when to leave for this route at "
            "this hour. The calendar event will only show your arrival time.",
        )
        self.assertContains(page, "Add arrival time to calendar: Mon, Nov 2, 09:15")

    def test_cheapest_no_data_shows_start_time_label(self):
        page = self.page(self.cheapest_plan)
        self.assertContains(
            page,
            "⚠ Not enough past trips to find the cheapest hour for this route. "
            "The calendar event will only show your start time.",
        )
        self.assertContains(page, "Add start time to calendar: Fri, Nov 6, 22:37")

    def test_repeat_checkbox_unticked_by_default(self):
        page = self.page(self.arrive_plan)
        self.assertContains(
            page,
            '<input type="checkbox" name="repeat" value="weekly"> Repeat every week',
        )

    def test_form_targets_calendar_url_with_get(self):
        page = self.page(self.arrive_plan)
        action = self.url("plan_calendar", self.arrive_plan)
        self.assertContains(page, f'<form method="get" action="{action}"')
