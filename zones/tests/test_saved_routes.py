from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from zones.models import SavedRoute, Zone


class SaveRouteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("alex@example.com")
        cls.other = get_user_model().objects.create_user("other@example.com")
        cls.pickup = Zone.objects.create(zone_id=1, name="Office", borough="Manhattan")
        cls.dropoff = Zone.objects.create(zone_id=2, name="Home", borough="Queens")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("zones:save_route")
        self.data = {"name": "Weekday commute", "pickup_zone": 1, "dropoff_zone": 2}

    def test_save_uses_current_user_and_returns_only_the_created_route(self):
        self.data["user"] = self.other.pk
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 201)
        route = SavedRoute.objects.get()
        self.assertEqual(route.user, self.user)
        self.assertEqual(route.pickup_zone, self.pickup)
        self.assertEqual(route.dropoff_zone, self.dropoff)
        self.assertEqual(route.name, self.data["name"])
        self.assertIsNotNone(route.created_at)
        self.assertEqual(response.json(), {"id": route.pk, "name": route.name})

    def test_invalid_names_are_rejected(self):
        for name in ("", "   ", "x" * 51):
            with self.subTest(name=name):
                response = self.client.post(self.url, {**self.data, "name": name})
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json()["errors"]["name"])
        self.assertFalse(SavedRoute.objects.exists())

    def test_name_is_trimmed_and_fifty_characters_are_allowed(self):
        response = self.client.post(
            self.url, {**self.data, "name": " " + "x" * 50 + " "}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(SavedRoute.objects.get().name, "x" * 50)

    def test_duplicate_name_is_rejected_for_the_same_user(self):
        self.client.post(self.url, self.data)
        response = self.client.post(
            self.url, {**self.data, "name": " Weekday commute "}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already", response.json()["errors"]["name"][0])
        self.assertEqual(SavedRoute.objects.count(), 1)

    def test_different_users_can_use_the_same_name_without_seeing_each_others_data(
        self,
    ):
        self.client.post(self.url, self.data)
        self.client.force_login(self.other)
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(SavedRoute.objects.filter(user=self.other).count(), 1)
        self.assertNotEqual(
            response.json()["id"], SavedRoute.objects.get(user=self.user).pk
        )
        self.assertNotContains(self.client.get(reverse("zones:map")), self.data["name"])

    def route_fields(self):
        return {
            "name": self.data["name"],
            "pickup_zone": self.pickup,
            "dropoff_zone": self.dropoff,
        }

    def test_database_enforces_unique_names_per_user(self):
        self.client.post(self.url, self.data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SavedRoute.objects.create(user=self.user, **self.route_fields())

    def test_concurrent_duplicate_gets_a_validation_message(self):
        self.client.post(self.url, self.data)
        with patch(
            "zones.forms.SavedRouteForm.clean_name", return_value=self.data["name"]
        ):
            response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("already", response.json()["errors"]["name"][0])
        self.assertEqual(SavedRoute.objects.count(), 1)

    def test_both_zones_are_required_and_must_exist(self):
        for field in ("pickup_zone", "dropoff_zone"):
            for value in ("", "bad", 999, -1, "9" * 100):
                with self.subTest(field=field, value=value):
                    response = self.client.post(self.url, {**self.data, field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json()["errors"])
        self.assertFalse(SavedRoute.objects.exists())

    def test_trip_within_one_zone_is_valid(self):
        response = self.client.post(self.url, {**self.data, "dropoff_zone": 1})
        self.assertEqual(response.status_code, 201)

    def test_guest_sees_signin_prompt_and_cannot_save(self):
        self.client.logout()
        page = self.client.get(reverse("zones:map"))
        self.assertContains(page, "Sign in to save routes")
        self.assertNotContains(page, 'id="save-route-form"')
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["message"], "Sign in to save routes")
        self.assertFalse(SavedRoute.objects.exists())

    def test_signed_in_map_has_hidden_save_form_with_csrf(self):
        response = self.client.get(reverse("zones:map"))
        self.assertContains(response, 'id="save-route-form"')
        self.assertContains(response, 'id="save-route-panel" hidden')
        self.assertContains(response, "Save this route")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "hidden>Sign in to save routes</a>")

    def test_save_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.data).status_code, 403)
        client.get(reverse("zones:map"))
        response = client.post(
            self.url, self.data, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value
        )
        self.assertEqual(response.status_code, 201)

    def test_deleting_account_deletes_only_its_saved_routes(self):
        self.user.set_password("Route-test-password-42!")
        self.user.save()
        self.client.force_login(self.user)
        self.client.post(self.url, self.data)
        other_route = SavedRoute.objects.create(user=self.other, **self.route_fields())
        response = self.client.post(
            reverse("accounts:delete"), {"password": "Route-test-password-42!"}
        )
        self.assertRedirects(response, reverse("zones:map"))
        self.assertFalse(SavedRoute.objects.filter(user_id=self.user.pk).exists())
        self.assertTrue(SavedRoute.objects.filter(pk=other_route.pk).exists())
