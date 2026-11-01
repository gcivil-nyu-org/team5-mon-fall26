"""US17 #46: save and manage "Leave by" plans."""

from datetime import time
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from routes.forms import TripPlanForm
from routes.models import TripPlan
from zones.models import RouteHourStats, Zone

MONDAY, FRIDAY, SATURDAY = 0, 4, 5


class TripPlanTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user("alex@example.com")
        cls.other = User.objects.create_user("other@example.com")
        cls.pickup = Zone.objects.create(zone_id=1, name="Office", borough="Manhattan")
        cls.dropoff = Zone.objects.create(zone_id=2, name="Home", borough="Queens")
        cls.arrive_plan = TripPlan.objects.create(
            user=cls.user,
            name="Monday arrival",
            pickup_zone=cls.pickup,
            dropoff_zone=cls.dropoff,
            mode=TripPlan.ARRIVE_BY,
            day_of_week=MONDAY,
            time=time(9, 15),
        )
        cls.cheapest_plan = TripPlan.objects.create(
            user=cls.user,
            name="Friday night",
            pickup_zone=cls.pickup,
            dropoff_zone=cls.dropoff,
            mode=TripPlan.CHEAPEST,
            day_of_week=FRIDAY,
            time=time(22, 37),
        )
        cls.secret = TripPlan.objects.create(
            user=cls.other,
            name="Other person's plan",
            pickup_zone=cls.dropoff,
            dropoff_zone=cls.pickup,
            mode=TripPlan.ARRIVE_BY,
            day_of_week=MONDAY,
            time=time(8, 0),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def stats(self, day, hour, fare, duration=30, count=10):
        return RouteHourStats.objects.create(
            pickup_zone=self.pickup,
            dropoff_zone=self.dropoff,
            day_of_week=day,
            hour=hour,
            trip_count=count,
            avg_duration_min=duration,
            fare_min=Decimal("5.00"),
            fare_avg=Decimal(fare),
            fare_max=Decimal("60.00"),
        )

    def url(self, name, plan):
        return reverse(f"routes:{name}", args=[plan.pk])


class SavePlanTests(TripPlanTestCase):
    def save(self, **overrides):
        data = {
            "name": "New plan",
            "pickup_zone": 1,
            "dropoff_zone": 2,
            "mode": "arrive_by",
            "day_of_week": 2,
            "time": "08:45",
        }
        data.update(overrides)
        return self.client.post(reverse("routes:save_plan"), data)

    def test_signed_in_user_saves_an_arrive_by_plan(self):
        response = self.save()
        self.assertEqual(response.status_code, 201)
        plan = TripPlan.objects.get(pk=response.json()["id"])
        self.assertEqual(plan.user, self.user)
        self.assertEqual(
            (plan.mode, plan.day_of_week, plan.time), ("arrive_by", 2, time(8, 45))
        )

    def test_cheapest_plan_made_with_now_keeps_the_exact_time(self):
        response = self.save(name="Now", mode="cheapest", day_of_week=5, time="14:37")
        self.assertEqual(response.status_code, 201)
        plan = TripPlan.objects.get(name="Now")
        self.assertEqual((plan.day_of_week, plan.time), (5, time(14, 37)))

    def test_arrive_by_needs_a_quarter_hour(self):
        response = self.save(time="08:40")
        self.assertEqual(response.status_code, 400)
        self.assertIn("time", response.json()["errors"])

    def test_invalid_input_returns_400(self):
        for params in (
            {"name": ""},
            {"name": "x" * 51},
            {"mode": "fastest"},
            {"day_of_week": 7},
            {"time": "25:00"},
            {"pickup_zone": 999},
            {"dropoff_zone": ""},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.save(**params).status_code, 400)

    def test_names_are_unique_per_user(self):
        self.assertEqual(self.save(name="Monday arrival").status_code, 400)
        self.client.force_login(self.other)
        self.assertEqual(self.save(name="Monday arrival").status_code, 201)

    def test_guest_cannot_save(self):
        self.client.logout()
        self.assertEqual(self.save().status_code, 401)
        self.assertFalse(TripPlan.objects.filter(name="New plan").exists())

    def test_owner_always_comes_from_the_session(self):
        response = self.save(user=self.other.pk)
        self.assertEqual(TripPlan.objects.get(pk=response.json()["id"]).user, self.user)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(reverse("routes:save_plan")).status_code, 405)

    def test_concurrent_duplicate_gets_a_validation_message(self):
        # Another request saved "Monday arrival" after this one was validated.
        with patch(
            "routes.forms.TripPlanForm.clean_name", return_value="Monday arrival"
        ):
            response = self.save(name="Monday arrival")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already", response.json()["errors"]["name"][0])
        self.assertEqual(
            TripPlan.objects.filter(user=self.user, name="Monday arrival").count(), 1
        )

    def test_unrelated_integrity_error_is_reraised(self):
        form = TripPlanForm(
            self.user,
            {
                "name": "New plan",
                "pickup_zone": 1,
                "dropoff_zone": 2,
                "mode": "arrive_by",
                "day_of_week": 2,
                "time": "08:45",
            },
        )
        self.assertTrue(form.is_valid())
        error = IntegrityError("foreign key constraint failed")
        with patch.object(TripPlan.objects, "create", side_effect=error):
            with self.assertRaisesRegex(IntegrityError, "foreign key constraint"):
                form.save()

    def test_trip_plan_str_returns_its_name(self):
        self.assertEqual(str(self.arrive_plan), "Monday arrival")


class MyPlansTests(TripPlanTestCase):
    def test_lists_only_the_current_users_plans(self):
        page = self.client.get(reverse("routes:my_plans"))
        self.assertContains(page, "Monday arrival")
        self.assertContains(page, "Arrive by: Monday 09:15")
        self.assertContains(page, "Cheapest in the next 3 hours: Friday 22:37")
        self.assertContains(page, "Office → Home")
        self.assertNotContains(page, "Other person")

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        response = self.client.get(reverse("routes:my_plans"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:signin')}?next={reverse('routes:my_plans')}",
            fetch_redirect_response=False,
        )

    def test_map_header_links_to_plans(self):
        self.assertContains(
            self.client.get(reverse("zones:map")), reverse("routes:my_plans")
        )


class OpenPlanTests(TripPlanTestCase):
    def test_arrive_by_plan_shows_the_current_result(self):
        self.stats(MONDAY, 9, "20.00", duration=20)
        self.stats(MONDAY, 8, "12.34", duration=35)
        page = self.client.get(self.url("open_plan", self.arrive_plan))
        self.assertContains(page, "Arrive by Monday 09:15")
        self.assertContains(page, "Monday 08:30")  # same answer as /api/routes/leave-by
        self.assertContains(page, "$12.34")

    def test_cheapest_plan_lists_the_3_hours_across_midnight(self):
        self.stats(FRIDAY, 22, "30.00")
        self.stats(SATURDAY, 0, "21.00", duration=40)
        page = self.client.get(self.url("open_plan", self.cheapest_plan))
        self.assertContains(page, "Fri 22:00–22:59")
        self.assertContains(page, "Fri 23:00–23:59")
        self.assertContains(page, "Not enough data")
        self.assertContains(page, "Sat 00:00–00:59")
        self.assertContains(page, "$21.00 (cheapest)")
        self.assertContains(page, "Saturday 00:40")  # expected arrival

    def test_result_is_recalculated_not_stored(self):
        row = self.stats(FRIDAY, 22, "30.00")
        self.assertContains(
            self.client.get(self.url("open_plan", self.cheapest_plan)), "$30.00"
        )
        row.fare_avg = Decimal("25.50")
        row.save()
        self.assertContains(
            self.client.get(self.url("open_plan", self.cheapest_plan)), "$25.50"
        )

    def test_not_enough_data_is_shown(self):
        page = self.client.get(self.url("open_plan", self.cheapest_plan))
        self.assertContains(page, "None of these 3 hours has enough past trips")
        page = self.client.get(self.url("open_plan", self.arrive_plan))
        self.assertContains(page, "Not enough data")

    def test_other_users_plan_is_404(self):
        self.assertEqual(
            self.client.get(self.url("open_plan", self.secret)).status_code, 404
        )


class EditPlanTests(TripPlanTestCase):
    def test_changing_day_and_time_updates_the_result(self):
        self.stats(MONDAY, 8, "12.00", duration=30)
        self.stats(MONDAY, 7, "11.00", duration=30)
        self.stats(SATURDAY, 8, "40.00", duration=10)
        response = self.client.post(
            self.url("edit_plan", self.arrive_plan), {"day_of_week": 5, "time": "08:30"}
        )
        self.assertRedirects(response, self.url("open_plan", self.arrive_plan))
        self.arrive_plan.refresh_from_db()
        self.assertEqual(
            (self.arrive_plan.day_of_week, self.arrive_plan.time), (5, time(8, 30))
        )
        page = self.client.get(self.url("open_plan", self.arrive_plan))
        self.assertContains(page, "Arrive by Saturday 08:30")
        self.assertContains(page, "$40.00")

    def test_arrive_by_edit_needs_a_quarter_hour(self):
        page = self.client.post(
            self.url("edit_plan", self.arrive_plan), {"day_of_week": 0, "time": "08:40"}
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "15-minute steps")
        self.arrive_plan.refresh_from_db()
        self.assertEqual(self.arrive_plan.time, time(9, 15))

    def test_cheapest_plan_keeps_any_minute(self):
        self.client.post(
            self.url("edit_plan", self.cheapest_plan),
            {"day_of_week": 6, "time": "22:37"},
        )
        self.cheapest_plan.refresh_from_db()
        self.assertEqual(self.cheapest_plan.day_of_week, 6)

    def test_edit_form_is_prefilled(self):
        page = self.client.get(self.url("edit_plan", self.arrive_plan))
        self.assertContains(page, 'value="09:15"')
        self.assertContains(page, "Arrival time")

    def test_other_users_plan_cannot_be_edited(self):
        response = self.client.post(
            self.url("edit_plan", self.secret), {"day_of_week": 3, "time": "10:00"}
        )
        self.assertEqual(response.status_code, 404)
        self.secret.refresh_from_db()
        self.assertEqual(self.secret.day_of_week, MONDAY)


class DeletePlanTests(TripPlanTestCase):
    def test_get_asks_and_post_deletes(self):
        page = self.client.get(self.url("delete_plan", self.arrive_plan))
        self.assertContains(page, "Delete plan?")
        self.assertTrue(TripPlan.objects.filter(pk=self.arrive_plan.pk).exists())
        response = self.client.post(self.url("delete_plan", self.arrive_plan))
        self.assertRedirects(response, reverse("routes:my_plans"))
        self.assertFalse(TripPlan.objects.filter(pk=self.arrive_plan.pk).exists())

    def test_other_users_plan_cannot_be_deleted(self):
        response = self.client.post(self.url("delete_plan", self.secret))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(TripPlan.objects.filter(pk=self.secret.pk).exists())

    def test_deleting_the_user_deletes_their_plans(self):
        self.user.delete()
        self.assertFalse(TripPlan.objects.filter(name="Monday arrival").exists())
        self.assertTrue(TripPlan.objects.filter(pk=self.secret.pk).exists())


class MapSavePlanTests(TripPlanTestCase):
    def test_signed_in_user_gets_the_save_form(self):
        page = self.client.get(reverse("zones:map"))
        self.assertContains(page, 'id="save-plan-form"')
        self.assertContains(page, "Save this plan")
        self.assertContains(page, "routes/js/save-plan.js")

    def test_guest_gets_a_sign_in_link_instead(self):
        self.client.logout()
        page = self.client.get(reverse("zones:map"))
        self.assertNotContains(page, 'id="save-plan-form"')
        self.assertContains(page, "Sign in to save this plan")
