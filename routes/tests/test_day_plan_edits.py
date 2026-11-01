"""US20 #49: editing a saved day plan (Pass B)."""

from datetime import time

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from routes.day_plans import (
    DayPlanError,
    add_stop,
    move_stop,
    remove_stop,
    reorder_stops,
    set_leave_time,
)
from routes.models import DayPlan, DayPlanStop
from routes.tests.test_day_plans import (
    BATTERY_PARK,
    BROOKLYN_HEIGHTS,
    MIDTOWN_CENTER,
    MONDAY,
    SATURDAY,
    TIMES_SQ,
    DayPlanTestCase,
)
from zones.models import Zone

CENTRAL_PARK, UNKNOWN = 43, 264


class DayPlanEditTestCase(DayPlanTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.zones[CENTRAL_PARK] = Zone.objects.create(
            zone_id=CENTRAL_PARK, name="Central Park", borough="Manhattan"
        )
        Zone.objects.create(zone_id=UNKNOWN, name="Unknown", borough="Unknown")
        # The worked example: 4 stops, 3 legs.
        cls.example = cls.make_plan(
            cls.user,
            "Worked example",
            [BROOKLYN_HEIGHTS, MIDTOWN_CENTER, TIMES_SQ, BATTERY_PARK],
            [time(8, 0), time(11, 15), time(13, 30)],
        )

    def stops(self, plan=None):
        """[(position, zone id, "HH:MM" or None)] in order."""
        plan = plan or self.example
        return [
            (s.position, s.zone_id, s.leave_label or None)
            for s in DayPlanStop.objects.filter(day_plan=plan).order_by("position")
        ]

    def stop_id(self, zone_id, plan=None):
        return (plan or self.example).stops.get(zone_id=zone_id).pk

    def ids(self, plan=None):
        return list(
            (plan or self.example)
            .stops.order_by("position")
            .values_list("pk", flat=True)
        )


class DayPlanRulesTests(DayPlanEditTestCase):
    ORIGINAL = [
        (0, BROOKLYN_HEIGHTS, "08:00"),
        (1, MIDTOWN_CENTER, "11:15"),
        (2, TIMES_SQ, "13:30"),
        (3, BATTERY_PARK, None),
    ]

    def test_move_up_swaps_zones_times_stay(self):
        move_stop(self.example, self.stop_id(BATTERY_PARK), "up")
        self.assertEqual(
            self.stops(),
            [
                (0, BROOKLYN_HEIGHTS, "08:00"),
                (1, MIDTOWN_CENTER, "11:15"),
                (2, BATTERY_PARK, "13:30"),
                (3, TIMES_SQ, None),
            ],
        )

    def test_move_down(self):
        move_stop(self.example, self.stop_id(BROOKLYN_HEIGHTS), "down")
        self.assertEqual(
            [zone for _, zone, _ in self.stops()],
            [MIDTOWN_CENTER, BROOKLYN_HEIGHTS, TIMES_SQ, BATTERY_PARK],
        )

    def test_move_first_up_or_last_down_is_blocked(self):
        with self.assertRaisesMessage(DayPlanError, "already the first"):
            move_stop(self.example, self.stop_id(BROOKLYN_HEIGHTS), "up")
        with self.assertRaisesMessage(DayPlanError, "already the last"):
            move_stop(self.example, self.stop_id(BATTERY_PARK), "down")
        self.assertEqual(self.stops(), self.ORIGINAL)

    def test_reorder_reassigns_zones_by_position(self):
        bh, mc, ts, bp = self.ids()
        reorder_stops(self.example, [ts, bh, mc, bp])
        self.assertEqual(
            self.stops(),
            [
                (0, TIMES_SQ, "08:00"),
                (1, BROOKLYN_HEIGHTS, "11:15"),
                (2, MIDTOWN_CENTER, "13:30"),
                (3, BATTERY_PARK, None),
            ],
        )

    def test_reorder_must_be_a_permutation(self):
        bh, mc, ts, bp = self.ids()
        other = self.plan.stops.first().pk
        for order in (
            [bh, mc, ts],
            [bh, mc, ts, ts],
            [bh, mc, ts, other],
            [bh, mc, ts, bp, 0],
        ):
            with self.subTest(order=order):
                with self.assertRaisesMessage(DayPlanError, "stops have changed"):
                    reorder_stops(self.example, order)
        self.assertEqual(self.stops(), self.ORIGINAL)

    def test_remove_middle_merges_legs(self):
        remove_stop(self.example, self.stop_id(MIDTOWN_CENTER))
        self.assertEqual(
            self.stops(),
            [
                (0, BROOKLYN_HEIGHTS, "08:00"),
                (1, TIMES_SQ, "13:30"),
                (2, BATTERY_PARK, None),
            ],
        )

    def test_remove_first(self):
        remove_stop(self.example, self.stop_id(BROOKLYN_HEIGHTS))
        self.assertEqual(
            self.stops(),
            [
                (0, MIDTOWN_CENTER, "11:15"),
                (1, TIMES_SQ, "13:30"),
                (2, BATTERY_PARK, None),
            ],
        )

    def test_remove_last_clears_new_last_time(self):
        remove_stop(self.example, self.stop_id(BATTERY_PARK))
        self.assertEqual(
            self.stops(),
            [
                (0, BROOKLYN_HEIGHTS, "08:00"),
                (1, MIDTOWN_CENTER, "11:15"),
                (2, TIMES_SQ, None),
            ],
        )

    def test_remove_blocked_at_three_stops(self):
        with self.assertRaisesMessage(
            DayPlanError,
            "A day plan needs at least 3 stops (2 trips). "
            "Add a stop before removing one.",
        ):
            remove_stop(self.plan, self.stop_id(MIDTOWN_CENTER, self.plan))
        self.assertEqual(self.plan.stops.count(), 3)

    def test_add_sets_previous_last_time(self):
        add_stop(self.example, self.zones[CENTRAL_PARK], time(16, 0))
        self.assertEqual(
            self.stops(),
            self.ORIGINAL[:3] + [(3, BATTERY_PARK, "16:00"), (4, CENTRAL_PARK, None)],
        )

    def test_add_blocked_at_ten_stops(self):
        for _ in range(6):
            add_stop(self.example, self.zones[CENTRAL_PARK], time(16, 0))
        self.assertEqual(self.example.stops.count(), 10)
        with self.assertRaisesMessage(DayPlanError, "at most 10 stops"):
            add_stop(self.example, self.zones[CENTRAL_PARK], time(17, 0))
        self.assertEqual(self.example.stops.count(), 10)

    def test_set_leave_time(self):
        set_leave_time(self.example, self.stop_id(MIDTOWN_CENTER), time(12, 45))
        self.assertEqual(self.stops()[1], (1, MIDTOWN_CENTER, "12:45"))
        with self.assertRaisesMessage(DayPlanError, "The last stop has no leave time."):
            set_leave_time(self.example, self.stop_id(BATTERY_PARK), time(18, 0))

    def test_stop_of_another_plan_is_rejected(self):
        with self.assertRaisesMessage(DayPlanError, "stops have changed"):
            remove_stop(self.example, self.plan.stops.first().pk)

    def test_positions_stay_0_to_n_minus_1(self):
        remove_stop(self.example, self.stop_id(BROOKLYN_HEIGHTS))
        add_stop(self.example, self.zones[CENTRAL_PARK], time(15, 0))
        move_stop(self.example, self.stop_id(CENTRAL_PARK), "up")
        remove_stop(self.example, self.stop_id(TIMES_SQ))
        positions = [p for p, _, _ in self.stops()]
        self.assertEqual(positions, list(range(len(positions))))
        self.assertIsNone(self.stops()[-1][2])  # only the last stop has no time
        self.assertTrue(all(leave for _, _, leave in self.stops()[:-1]))

    def test_changes_lock_the_plan_row(self):
        if not connection.features.has_select_for_update:
            self.skipTest("database has no SELECT ... FOR UPDATE")
        with CaptureQueriesContext(connection) as queries:
            move_stop(self.example, self.stop_id(BATTERY_PARK), "up")
        locks = [q["sql"] for q in queries if "FOR UPDATE" in q["sql"]]
        self.assertEqual(len(locks), 1)
        self.assertIn(DayPlan._meta.db_table, locks[0])


class DayPlanEditViewsTests(DayPlanEditTestCase):
    def page_url(self, plan=None):
        return self.url("open_day_plan", plan or self.example)

    def post(self, name, data=None, plan=None, stop_zone=None):
        plan = plan or self.example
        args = [plan.pk] + ([self.stop_id(stop_zone, plan)] if stop_zone else [])
        return self.client.post(reverse(f"routes:{name}", args=args), data or {})

    def assert_back_to_page(self, response, message):
        # Don't fetch the redirect here: that would use up the message.
        self.assertRedirects(response, self.page_url(), fetch_redirect_response=False)
        self.assertContains(self.client.get(self.page_url()), message)

    def test_page_shows_the_edit_forms(self):
        page = self.client.get(self.page_url())
        self.assertContains(
            page, reverse("routes:change_day_plan_day", args=[self.example.pk])
        )
        self.assertContains(
            page, reverse("routes:add_day_plan_stop", args=[self.example.pk])
        )
        self.assertContains(
            page, 'name="leave_time" step="900"', count=3
        )  # not the last stop
        self.assertContains(
            page, '<input type="time" name="leave_time" id="id_leave_time"'
        )
        self.assertContains(page, 'name="direction" value="up"', count=4)
        self.assertContains(page, 'aria-label="Move Brooklyn Heights up" disabled')
        self.assertContains(page, 'aria-label="Move Battery Park down" disabled')
        self.assertContains(page, "Leave Battery Park at")
        reorder_url = reverse("routes:reorder_day_plan", args=[self.example.pk])
        self.assertContains(page, f'data-reorder-url="{reorder_url}"')
        self.assertContains(page, "routes/vendor/sortable/Sortable.min.js")
        self.assertContains(page, "routes/js/day-plan-sort.js")
        self.assertContains(
            page, reverse("routes:delete_day_plan", args=[self.example.pk])
        )

    def test_stop_rows_are_numbered(self):
        page = self.client.get(self.page_url()).content.decode()
        rows = page.split('data-stop-id="')[1:]
        names = ["Brooklyn Heights", "Midtown Center", "Times Sq", "Battery Park"]
        self.assertEqual(len(rows), len(names))
        for number, (row, name) in enumerate(zip(rows, names), start=1):
            with self.subTest(number=number):
                self.assertIn(f'<span class="stop-number">{number}.</span>', row)
                self.assertIn(f'<span class="stop-name">{name}', row)

    def test_numbers_follow_the_new_order(self):
        self.post("move_day_plan_stop", {"direction": "up"}, stop_zone=BATTERY_PARK)
        page = self.client.get(self.page_url()).content.decode()
        third = page.split('data-stop-id="')[3]
        self.assertIn('<span class="stop-number">3.</span>', third)
        self.assertIn('<span class="stop-name">Battery Park', third)

    def test_change_day_updates_stats(self):
        self.stats(BROOKLYN_HEIGHTS, MIDTOWN_CENTER, 8, fare="19.75", day=SATURDAY)
        response = self.post("change_day_plan_day", {"day_of_week": SATURDAY})
        self.assert_back_to_page(response, "Day changed.")
        self.example.refresh_from_db()
        self.assertEqual(self.example.day_of_week, SATURDAY)
        self.assertContains(
            self.client.get(self.page_url()), "$10.00 / $19.75 / $40.00"
        )

    def test_change_day_rejects_bad_day(self):
        response = self.post("change_day_plan_day", {"day_of_week": 9})
        self.assertContains(response, 'role="alert"', status_code=400)
        self.example.refresh_from_db()
        self.assertEqual(self.example.day_of_week, MONDAY)

    def test_set_leave_time(self):
        response = self.post(
            "set_day_plan_stop_time", {"leave_time": "12:45"}, stop_zone=MIDTOWN_CENTER
        )
        self.assert_back_to_page(response, "Leave time changed.")
        self.assertEqual(self.stops()[1][2], "12:45")

    def test_set_leave_time_quarter_hour_only(self):
        for value in ("12:40", "noon", ""):
            with self.subTest(value=value):
                response = self.post(
                    "set_day_plan_stop_time",
                    {"leave_time": value},
                    stop_zone=MIDTOWN_CENTER,
                )
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stops()[1][2], "11:15")

    def test_last_stop_has_no_time_form(self):
        page = self.client.get(self.page_url()).content.decode()
        last_item = page.split('data-stop-id="')[-1]
        self.assertNotIn("set_day_plan_stop_time", last_item)
        self.assertNotIn(
            'name="leave_time" step="900" value=', last_item.split("</li>")[0]
        )
        response = self.post(
            "set_day_plan_stop_time", {"leave_time": "18:00"}, stop_zone=BATTERY_PARK
        )
        self.assertContains(
            response, "The last stop has no leave time.", status_code=400
        )

    def test_add_stop(self):
        response = self.post(
            "add_day_plan_stop", {"zone": CENTRAL_PARK, "leave_time": "16:00"}
        )
        self.assert_back_to_page(response, "Stop added.")
        self.assertEqual(
            self.stops()[-2:], [(3, BATTERY_PARK, "16:00"), (4, CENTRAL_PARK, None)]
        )
        self.assertContains(
            self.client.get(self.page_url()),
            "4. Battery Park → Central Park, leave 16:00",
        )

    def test_add_stop_rejects_bad_input(self):
        cases = [
            {"zone": UNKNOWN, "leave_time": "16:00"},  # no shape
            {"zone": 999, "leave_time": "16:00"},
            {"zone": CENTRAL_PARK, "leave_time": "16:10"},
            {"zone": CENTRAL_PARK, "leave_time": ""},
        ]
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.post("add_day_plan_stop", data).status_code, 400)
        self.assertEqual(self.example.stops.count(), 4)

    def test_add_stop_blocked_at_ten_stops(self):
        for _ in range(6):
            add_stop(self.example, self.zones[CENTRAL_PARK], time(16, 0))
        page = self.client.get(self.page_url())
        self.assertContains(page, "A day plan can have at most 10 stops.")
        self.assertNotContains(
            page, reverse("routes:add_day_plan_stop", args=[self.example.pk])
        )
        response = self.post(
            "add_day_plan_stop", {"zone": CENTRAL_PARK, "leave_time": "17:00"}
        )
        self.assertContains(response, "at most 10 stops", status_code=400)

    def test_add_stop_dropdown_sorted_by_borough_then_name_without_264_265(self):
        page = self.client.get(self.page_url()).content.decode()
        options = page.split('name="zone"')[1].split("</select>")[0]
        labels = [
            part.split("</option>")[0].split(">")[-1]
            for part in options.split("<option")[2:]
        ]
        self.assertEqual(
            labels,
            [
                "Brooklyn: Brooklyn Heights",
                "Manhattan: Battery Park",
                "Manhattan: Central Park",
                "Manhattan: Midtown Center",
                "Manhattan: Times Sq/Theatre District",
            ],
        )
        self.assertNotIn("Unknown", options)

    def test_up_down_buttons_post_and_page_shows_new_legs(self):
        response = self.post(
            "move_day_plan_stop", {"direction": "up"}, stop_zone=BATTERY_PARK
        )
        self.assert_back_to_page(response, "Stops reordered.")
        page = self.client.get(self.page_url())
        self.assertContains(page, "2. Midtown Center → Battery Park, leave 11:15")
        self.assertContains(
            page, "3. Battery Park → Times Sq/Theatre District, leave 13:30"
        )

    def test_move_first_up_shows_a_message(self):
        response = self.post(
            "move_day_plan_stop", {"direction": "up"}, stop_zone=BROOKLYN_HEIGHTS
        )
        self.assertContains(
            response, "This stop is already the first.", status_code=400
        )
        response = self.post(
            "move_day_plan_stop", {"direction": "sideways"}, stop_zone=TIMES_SQ
        )
        self.assertEqual(response.status_code, 400)

    def test_remove_button_then_page_shows_merged_leg(self):
        response = self.post("remove_day_plan_stop", stop_zone=MIDTOWN_CENTER)
        self.assert_back_to_page(response, "Stop removed.")
        page = self.client.get(self.page_url())
        self.assertContains(
            page, "1. Brooklyn Heights → Times Sq/Theatre District, leave 08:00"
        )
        self.assertContains(page, "3 stops, 2 trips")

    def test_remove_blocked_at_three_stops_with_message(self):
        response = self.post(
            "remove_day_plan_stop", plan=self.plan, stop_zone=MIDTOWN_CENTER
        )
        self.assertContains(
            response,
            "A day plan needs at least 3 stops (2 trips). "
            "Add a stop before removing one.",
            status_code=400,
        )
        self.assertEqual(self.plan.stops.count(), 3)

    def test_reorder_endpoint_json_and_page_updates(self):
        bh, mc, ts, bp = self.ids()
        response = self.post("reorder_day_plan", {"order": f"{ts},{bh},{mc},{bp}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertContains(
            self.client.get(self.page_url()),
            "1. Times Sq/Theatre District → Brooklyn Heights, leave 08:00",
        )

    def test_reorder_endpoint_rejects_a_wrong_order(self):
        bh, mc, ts, bp = self.ids()
        for order in (f"{bh},{mc},{ts}", f"{bh},{bh},{mc},{ts}", "a,b", ""):
            with self.subTest(order=order):
                response = self.post("reorder_day_plan", {"order": order})
                self.assertEqual(response.status_code, 400)
                self.assertIn("stops have changed", response.json()["error"])
        self.assertEqual(self.stops(), DayPlanRulesTests.ORIGINAL)

    def test_delete_confirms_then_deletes(self):
        url = self.url("delete_day_plan", self.example)
        page = self.client.get(url)
        self.assertContains(
            page, "Delete <strong>Worked example</strong> (Monday, 4 stops)"
        )
        self.assertTrue(DayPlan.objects.filter(pk=self.example.pk).exists())
        response = self.client.post(url)
        self.assertRedirects(
            response, reverse("routes:my_day_plans"), fetch_redirect_response=False
        )
        self.assertFalse(DayPlan.objects.filter(pk=self.example.pk).exists())
        self.assertFalse(
            DayPlanStop.objects.filter(day_plan_id=self.example.pk).exists()
        )
        self.assertContains(
            self.client.get(reverse("routes:my_day_plans")), "Day plan deleted."
        )

    def test_list_has_a_delete_link(self):
        self.assertContains(
            self.client.get(reverse("routes:my_day_plans")),
            reverse("routes:delete_day_plan", args=[self.example.pk]),
        )


class DayPlanEditAccessTests(DayPlanEditTestCase):
    """Ownership, sign-in, methods and CSRF for every Pass B endpoint."""

    def endpoints(self):
        plan, stop = self.example.pk, self.stop_id(MIDTOWN_CENTER)
        return {
            "change_day_plan_day": ([plan], {"day_of_week": 2}),
            "add_day_plan_stop": (
                [plan],
                {"zone": CENTRAL_PARK, "leave_time": "16:00"},
            ),
            "set_day_plan_stop_time": ([plan, stop], {"leave_time": "12:00"}),
            "move_day_plan_stop": ([plan, stop], {"direction": "up"}),
            "remove_day_plan_stop": ([plan, stop], {}),
            "reorder_day_plan": ([plan], {"order": ",".join(map(str, self.ids()))}),
            "delete_day_plan": ([plan], {}),
        }

    def assert_unchanged(self):
        self.assertTrue(DayPlan.objects.filter(pk=self.example.pk).exists())
        self.assertEqual(self.stops(), DayPlanRulesTests.ORIGINAL)
        self.example.refresh_from_db()
        self.assertEqual(self.example.day_of_week, MONDAY)

    def test_other_users_plan_is_404(self):
        self.client.force_login(self.other)
        for name, (args, data) in self.endpoints().items():
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.post(
                        reverse(f"routes:{name}", args=args), data
                    ).status_code,
                    404,
                )
        self.assertEqual(
            self.client.get(self.url("delete_day_plan", self.example)).status_code, 404
        )
        self.assert_unchanged()

    def test_stop_from_another_plan_is_404(self):
        foreign = self.plan.stops.get(position=1).pk
        for name in (
            "set_day_plan_stop_time",
            "move_day_plan_stop",
            "remove_day_plan_stop",
        ):
            with self.subTest(name=name):
                url = reverse(f"routes:{name}", args=[self.example.pk, foreign])
                data = {"leave_time": "12:00", "direction": "up"}
                self.assertEqual(self.client.post(url, data).status_code, 404)
        self.assert_unchanged()

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        for name, (args, data) in self.endpoints().items():
            with self.subTest(name=name):
                url = reverse(f"routes:{name}", args=args)
                self.assertRedirects(
                    self.client.post(url, data),
                    f"{reverse('accounts:signin')}?next={url}",
                    fetch_redirect_response=False,
                )
        self.assert_unchanged()

    def test_post_only_views_reject_get(self):
        for name, (args, _) in self.endpoints().items():
            if name == "delete_day_plan":
                continue  # GET shows the confirmation page
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(reverse(f"routes:{name}", args=args)).status_code,
                    405,
                )

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for name, (args, data) in self.endpoints().items():
            with self.subTest(name=name):
                self.assertEqual(
                    client.post(reverse(f"routes:{name}", args=args), data).status_code,
                    403,
                )
        self.assert_unchanged()
