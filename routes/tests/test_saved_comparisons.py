"""US23 #70: Save a comparison (two zones from the compare page, US22)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.html import escape

from routes.models import SavedComparison
from zones.models import Zone

NAME_TAKEN = "You already have a saved comparison with this name."
SAME_ZONES = "Choose two different zones."


class ComparisonTestData(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("alex@example.com")
        cls.other = get_user_model().objects.create_user("other@example.com")
        cls.midtown = Zone.objects.create(
            zone_id=161, name="Midtown Center", borough="Manhattan"
        )
        cls.jfk = Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")
        cls.astoria = Zone.objects.create(zone_id=7, name="Astoria", borough="Queens")
        # In the zone table but not on the map (no shape).
        cls.unknown = Zone.objects.create(
            zone_id=264, name="Unknown", borough="Unknown"
        )

    def setUp(self):
        self.client.force_login(self.user)


class SaveComparisonTests(ComparisonTestData):
    def setUp(self):
        super().setUp()
        self.url = reverse("routes:save_comparison")
        self.data = {"name": "Work vs airport", "zone_a": 161, "zone_b": 132}

    def test_url(self):
        self.assertEqual(self.url, "/comparisons/save/")

    def test_save_uses_the_current_user_and_keeps_the_order_picked(self):
        self.data["user"] = self.other.pk
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 201)
        comparison = SavedComparison.objects.get()
        self.assertEqual(
            response.json(), {"id": comparison.pk, "name": "Work vs airport"}
        )
        self.assertEqual(comparison.user, self.user)
        self.assertEqual(comparison.zone_a, self.midtown)
        self.assertEqual(comparison.zone_b, self.jfk)

        self.client.post(self.url, {"name": "Reversed", "zone_a": 132, "zone_b": 161})
        reversed_pair = SavedComparison.objects.get(name="Reversed")
        self.assertEqual(reversed_pair.zone_a, self.jfk)
        self.assertEqual(reversed_pair.zone_b, self.midtown)

    def test_saved_comparison_appears_in_my_comparisons(self):
        self.client.post(self.url, self.data)
        page = self.client.get(reverse("routes:my_comparisons"))
        self.assertContains(page, "Work vs airport")
        self.assertContains(page, "Midtown Center")
        self.assertContains(page, "JFK Airport")

    def test_invalid_names_are_rejected(self):
        for name in ["", "   ", "x" * 51]:
            with self.subTest(name=name):
                response = self.client.post(self.url, {**self.data, "name": name})
                self.assertEqual(response.status_code, 400)
                self.assertIn("name", response.json()["errors"])
        self.assertFalse(SavedComparison.objects.exists())

    def test_name_is_trimmed_and_fifty_characters_are_allowed(self):
        response = self.client.post(self.url, {**self.data, "name": "  Commute  "})
        self.assertEqual(response.json()["name"], "Commute")
        response = self.client.post(self.url, {**self.data, "name": "y" * 50})
        self.assertEqual(response.status_code, 201)

    def test_duplicate_name_is_rejected_for_the_same_user(self):
        self.client.post(self.url, self.data)
        response = self.client.post(self.url, {**self.data, "zone_a": 7, "zone_b": 161})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["name"], [NAME_TAKEN])
        self.assertEqual(SavedComparison.objects.count(), 1)

    def test_names_are_case_sensitive_like_saved_routes(self):
        self.client.post(self.url, self.data)
        response = self.client.post(self.url, {**self.data, "name": "WORK VS AIRPORT"})
        self.assertEqual(response.status_code, 201)

    def test_another_user_can_reuse_a_name(self):
        SavedComparison.objects.create(
            user=self.other,
            name="Work vs airport",
            zone_a=self.jfk,
            zone_b=self.astoria,
        )
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 201)

    def test_zone_a_and_zone_b_must_differ(self):
        response = self.client.post(self.url, {**self.data, "zone_b": 161})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["zone_b"], [SAME_ZONES])
        self.assertFalse(SavedComparison.objects.exists())

    def test_zones_must_be_known_and_on_the_map(self):
        for zone_a, zone_b in [("", 132), (161, ""), (999, 132), (161, 264), ("x", 1)]:
            with self.subTest(zone_a=zone_a, zone_b=zone_b):
                response = self.client.post(
                    self.url, {**self.data, "zone_a": zone_a, "zone_b": zone_b}
                )
                self.assertEqual(response.status_code, 400)
        self.assertFalse(SavedComparison.objects.exists())

    def test_guest_gets_401_and_nothing_is_saved(self):
        self.client.logout()
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["message"], "Sign in to save comparisons")
        self.assertFalse(SavedComparison.objects.exists())

    def test_save_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.data).status_code, 403)
        client.get(reverse("zones:compare"))
        response = client.post(
            self.url, self.data, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value
        )
        self.assertEqual(response.status_code, 201)

    def test_concurrent_duplicate_gets_the_name_message(self):
        # A second request saved the same name after this one was validated.
        self.client.post(self.url, self.data)
        with patch(
            "routes.forms.SavedComparisonForm.clean_name",
            return_value=self.data["name"],
        ):
            response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["name"], [NAME_TAKEN])
        self.assertEqual(SavedComparison.objects.count(), 1)

    def test_unrelated_integrity_error_is_reraised(self):
        with patch.object(
            SavedComparison.objects, "create", side_effect=IntegrityError("other")
        ):
            with self.assertRaises(IntegrityError):
                self.client.post(self.url, self.data)


class SavedComparisonModelTests(ComparisonTestData):
    def test_database_enforces_unique_names_per_user(self):
        SavedComparison.objects.create(
            user=self.user, name="Same", zone_a=self.midtown, zone_b=self.jfk
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SavedComparison.objects.create(
                user=self.user, name="Same", zone_a=self.jfk, zone_b=self.astoria
            )

    def test_database_rejects_the_same_zone_for_a_and_b(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SavedComparison.objects.create(
                user=self.user, name="Twice", zone_a=self.jfk, zone_b=self.jfk
            )

    def test_str_is_the_name(self):
        comparison = SavedComparison(name="Work vs airport")
        self.assertEqual(str(comparison), "Work vs airport")

    def test_deleting_the_user_deletes_their_saved_comparisons(self):
        SavedComparison.objects.create(
            user=self.user, name="Mine", zone_a=self.midtown, zone_b=self.jfk
        )
        theirs = SavedComparison.objects.create(
            user=self.other, name="Theirs", zone_a=self.midtown, zone_b=self.jfk
        )
        self.user.delete()
        self.assertEqual(list(SavedComparison.objects.all()), [theirs])

    def test_delete_my_account_page_deletes_saved_comparisons(self):
        self.user.set_password("Compare-test-password-42!")
        self.user.save()
        self.client.force_login(self.user)
        SavedComparison.objects.create(
            user=self.user, name="Mine", zone_a=self.midtown, zone_b=self.jfk
        )
        response = self.client.post(
            reverse("accounts:delete"), {"password": "Compare-test-password-42!"}
        )
        self.assertRedirects(response, reverse("zones:map"))
        self.assertFalse(SavedComparison.objects.exists())


class ManageSavedComparisonsTests(ComparisonTestData):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.comparison = SavedComparison.objects.create(
            user=cls.user, name="Work vs airport", zone_a=cls.midtown, zone_b=cls.jfk
        )
        cls.private = SavedComparison.objects.create(
            user=cls.other,
            name="Other person's secret",
            zone_a=cls.astoria,
            zone_b=cls.midtown,
        )

    def url(self, action, comparison=None):
        return reverse(f"routes:{action}", args=[(comparison or self.comparison).pk])

    def test_urls(self):
        pk = self.comparison.pk
        self.assertEqual(reverse("routes:my_comparisons"), "/comparisons/")
        self.assertEqual(self.url("open_comparison"), f"/comparisons/{pk}/open/")
        self.assertEqual(self.url("rename_comparison"), f"/comparisons/{pk}/rename/")
        self.assertEqual(self.url("delete_comparison"), f"/comparisons/{pk}/delete/")

    def test_my_comparisons_lists_only_my_comparisons(self):
        page = self.client.get(reverse("routes:my_comparisons"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "<h1>My comparisons</h1>", html=True)
        self.assertContains(page, "Work vs airport")
        self.assertContains(page, "Midtown Center")
        self.assertContains(page, "JFK Airport")
        self.assertContains(page, self.comparison.created_at.strftime("%b"))
        for action in ("open_comparison", "rename_comparison", "delete_comparison"):
            self.assertContains(page, self.url(action))
            self.assertNotContains(page, self.url(action, self.private))
        self.assertNotContains(page, escape(self.private.name))
        self.assertContains(page, "routes/css/routes.css")

    def test_empty_list(self):
        self.comparison.delete()
        page = self.client.get(reverse("routes:my_comparisons"))
        self.assertContains(page, "No saved comparisons yet")
        self.assertContains(page, reverse("zones:compare"))

    def test_open_shows_compare_mode_with_both_zones(self):
        page = self.client.get(self.url("open_comparison"))
        self.assertEqual(page.status_code, 200)
        self.assertTemplateUsed(page, "zones/compare.html")
        self.assertContains(page, 'data-start-a="161"')
        self.assertContains(page, 'data-start-b="132"')
        self.assertContains(page, 'data-saved-a="161"')
        self.assertContains(page, 'data-saved-b="132"')
        self.assertContains(page, "Saved comparison: Work vs airport")
        self.assertContains(page, "zones/js/compare.js")

    def test_open_ignores_zones_in_the_address_but_keeps_day_and_hour(self):
        page = self.client.get(
            self.url("open_comparison"), {"a": 7, "b": 161, "day": 4, "hour": 9}
        )
        self.assertContains(page, 'data-start-a="161"')
        self.assertContains(page, 'data-start-b="132"')
        self.assertContains(page, '<option value="4" selected>Friday</option>')
        self.assertContains(page, "9:00–9:59")

    def test_plain_compare_page_has_no_saved_heading(self):
        page = self.client.get(reverse("zones:compare"), {"a": 161, "b": 132})
        self.assertNotContains(page, "Saved comparison:")
        self.assertNotContains(page, "data-saved-a")

    def test_rename_uses_the_same_name_rules(self):
        url = self.url("rename_comparison")
        page = self.client.get(url)
        self.assertContains(page, 'value="Work vs airport"')
        self.assertContains(page, "csrfmiddlewaretoken")
        for name in ["", "x" * 51]:
            with self.subTest(name=name):
                response = self.client.post(url, {"name": name})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors["name"])
        response = self.client.post(url, {"name": "  Office vs JFK  "})
        self.assertRedirects(response, reverse("routes:my_comparisons"))
        self.comparison.refresh_from_db()
        self.assertEqual(self.comparison.name, "Office vs JFK")

    def test_rename_to_the_same_name_is_allowed(self):
        response = self.client.post(
            self.url("rename_comparison"), {"name": "Work vs airport"}
        )
        self.assertRedirects(response, reverse("routes:my_comparisons"))

    def test_rename_to_a_name_already_used_is_rejected(self):
        SavedComparison.objects.create(
            user=self.user, name="Taken", zone_a=self.astoria, zone_b=self.jfk
        )
        response = self.client.post(self.url("rename_comparison"), {"name": "Taken"})
        self.assertContains(response, NAME_TAKEN)
        self.comparison.refresh_from_db()
        self.assertEqual(self.comparison.name, "Work vs airport")
        # Another user's name is no obstacle.
        response = self.client.post(
            self.url("rename_comparison"), {"name": "Other person's secret"}
        )
        self.assertRedirects(response, reverse("routes:my_comparisons"))

    def test_concurrent_duplicate_rename_shows_the_name_message(self):
        SavedComparison.objects.create(
            user=self.user, name="Raced", zone_a=self.astoria, zone_b=self.jfk
        )
        with patch("routes.forms.ComparisonNameForm.clean_name", return_value="Raced"):
            response = self.client.post(
                self.url("rename_comparison"), {"name": "Raced"}
            )
        self.assertContains(response, NAME_TAKEN)
        self.comparison.refresh_from_db()
        self.assertEqual(self.comparison.name, "Work vs airport")

    def test_unrelated_rename_integrity_error_is_reraised(self):
        with patch(
            "routes.views.SavedComparison.save", side_effect=IntegrityError("x")
        ):
            with self.assertRaises(IntegrityError):
                self.client.post(self.url("rename_comparison"), {"name": "New"})

    def test_delete_asks_first_then_deletes_only_that_comparison(self):
        url = self.url("delete_comparison")
        page = self.client.get(url)
        self.assertContains(page, "Delete comparison?")
        self.assertContains(page, "csrfmiddlewaretoken")
        self.assertTrue(SavedComparison.objects.filter(pk=self.comparison.pk).exists())
        response = self.client.post(url)
        self.assertRedirects(response, reverse("routes:my_comparisons"))
        self.assertFalse(SavedComparison.objects.filter(pk=self.comparison.pk).exists())
        self.assertTrue(SavedComparison.objects.filter(pk=self.private.pk).exists())

    def test_other_users_comparisons_are_404_for_every_operation(self):
        for action in ("open_comparison", "rename_comparison", "delete_comparison"):
            url = self.url(action, self.private)
            with self.subTest(action=action, method="GET"):
                self.assertEqual(self.client.get(url).status_code, 404)
            if action != "open_comparison":
                with self.subTest(action=action, method="POST"):
                    response = self.client.post(url, {"name": "Stolen"})
                    self.assertEqual(response.status_code, 404)
        self.private.refresh_from_db()
        self.assertEqual(self.private.name, "Other person's secret")

    def test_missing_comparison_is_404(self):
        for action in ("open_comparison", "rename_comparison", "delete_comparison"):
            url = reverse(f"routes:{action}", args=[999999])
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        for url in (
            reverse("routes:my_comparisons"),
            self.url("open_comparison"),
            self.url("rename_comparison"),
            self.url("delete_comparison"),
        ):
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url),
                    f"{reverse('accounts:signin')}?next={url}",
                    fetch_redirect_response=False,
                )

    def test_rename_and_delete_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for action in ("rename_comparison", "delete_comparison"):
            response = client.post(self.url(action), {"name": "No token"})
            self.assertEqual(response.status_code, 403)
        self.assertTrue(SavedComparison.objects.filter(pk=self.comparison.pk).exists())


class ComparisonLinksTests(ComparisonTestData):
    def test_routes_pages_nav_links_to_my_comparisons(self):
        page = self.client.get(reverse("routes:my_routes"))
        self.assertContains(
            page,
            f'<a href="{reverse("routes:my_comparisons")}">Comparisons</a>',
            html=True,
        )

    def test_compare_card_links_to_my_comparisons(self):
        page = self.client.get(reverse("zones:compare"))
        self.assertContains(page, 'id="my-comparisons"')
        self.assertContains(page, reverse("routes:my_comparisons"))

    def test_map_page_does_not_link_to_my_comparisons(self):
        page = self.client.get(reverse("zones:map"))
        self.assertNotContains(page, reverse("routes:my_comparisons"))

    def test_signed_in_compare_card_has_a_hidden_save_row_with_csrf(self):
        page = self.client.get(reverse("zones:compare"))
        self.assertContains(
            page, 'id="save-comparison-panel" class="compare-save" hidden'
        )
        self.assertContains(page, 'id="save-comparison-form"')
        self.assertContains(page, reverse("routes:save_comparison"))
        self.assertContains(page, "Save this comparison")
        self.assertContains(page, "csrfmiddlewaretoken")
        self.assertContains(page, "hidden>Sign in to save comparisons</a>")

    def test_guest_compare_card_has_the_sign_in_prompt_and_no_form(self):
        self.client.logout()
        page = self.client.get(reverse("zones:compare"))
        self.assertContains(
            page, 'id="save-comparison-panel" class="compare-save" hidden'
        )
        self.assertNotContains(page, 'id="save-comparison-form"')
        self.assertContains(page, "Sign in to save comparisons")
