from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from routes.models import SavedRoute
from zones.models import Zone


class ManageSavedRoutesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("alex@example.com")
        cls.other = get_user_model().objects.create_user("other@example.com")
        cls.pickup = Zone.objects.create(zone_id=1, name="Office", borough="Manhattan")
        cls.dropoff = Zone.objects.create(zone_id=2, name="Home", borough="Queens")
        cls.route = SavedRoute.objects.create(
            user=cls.user,
            name="Commute",
            pickup_zone=cls.pickup,
            dropoff_zone=cls.dropoff,
        )
        cls.private_route = SavedRoute.objects.create(
            user=cls.other,
            name="Other person's secret",
            pickup_zone=cls.dropoff,
            dropoff_zone=cls.pickup,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def route_url(self, action, route=None):
        return reverse(f"routes:{action}", args=[(route or self.route).pk])

    def test_my_routes_lists_only_the_current_users_routes(self):
        page = self.client.get(reverse("routes:my_routes"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Commute")
        self.assertContains(page, "Office")
        self.assertContains(page, "Home")
        self.assertContains(page, self.route.created_at.strftime("%b"))
        self.assertContains(page, self.route_url("open_saved_route"))
        self.assertContains(page, self.route_url("rename_saved_route"))
        self.assertContains(page, self.route_url("delete_saved_route"))
        self.assertContains(page, "routes/css/routes.css")
        self.assertNotContains(page, "accounts/css/accounts.css")
        self.assertNotContains(page, self.private_route.name)
        self.assertNotContains(
            page, self.route_url("open_saved_route", self.private_route)
        )

    def test_empty_list_and_navigation(self):
        self.route.delete()
        page = self.client.get(reverse("routes:my_routes"))
        self.assertContains(page, "No saved routes yet")
        self.assertContains(page, reverse("zones:map"))
        self.assertContains(
            self.client.get(reverse("zones:map")), reverse("routes:my_routes")
        )
        self.assertNotContains(
            self.client.get(reverse("accounts:account")), reverse("routes:my_routes")
        )

    def test_open_route_renders_map_with_selection_and_summary_hooks(self):
        page = self.client.get(self.route_url("open_saved_route"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'data-saved-pickup="1"')
        self.assertContains(page, 'data-saved-dropoff="2"')
        self.assertContains(page, "Commute")
        self.assertContains(page, 'id="summary-panel"')
        self.assertContains(page, "zones/js/filters.js")

    def test_other_users_routes_are_404_for_every_operation(self):
        for action in ("open_saved_route", "rename_saved_route", "delete_saved_route"):
            url = self.route_url(action, self.private_route)
            with self.subTest(action=action, method="GET"):
                self.assertEqual(self.client.get(url).status_code, 404)
            if action != "open_saved_route":
                with self.subTest(action=action, method="POST"):
                    self.assertEqual(
                        self.client.post(url, {"name": "Stolen"}).status_code, 404
                    )
        self.assertEqual(self.private_route.name, "Other person's secret")

    def test_missing_route_is_404(self):
        for action in ("open_saved_route", "rename_saved_route", "delete_saved_route"):
            self.assertEqual(
                self.client.get(reverse(f"routes:{action}", args=[999999])).status_code,
                404,
            )

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()
        self.assertContains(
            self.client.get(reverse("zones:map")), reverse("routes:my_routes")
        )
        for url in (
            reverse("routes:my_routes"),
            self.route_url("open_saved_route"),
            self.route_url("rename_saved_route"),
            self.route_url("delete_saved_route"),
        ):
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url),
                    f"{reverse('accounts:signin')}?next={url}",
                    fetch_redirect_response=False,
                )

    def test_rename_uses_same_name_rules_as_save(self):
        url = self.route_url("rename_saved_route")
        for name in ("", "   ", "x" * 51):
            with self.subTest(name=name):
                page = self.client.post(url, {"name": name})
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, "errorlist")
                self.route.refresh_from_db()
                self.assertEqual(self.route.name, "Commute")
        page = self.client.post(url, {"name": "  New name  "})
        self.assertRedirects(page, reverse("routes:my_routes"))
        self.route.refresh_from_db()
        self.assertEqual(self.route.name, "New name")

    def test_rename_to_same_name_is_allowed(self):
        page = self.client.post(
            self.route_url("rename_saved_route"), {"name": "Commute"}
        )
        self.assertRedirects(page, reverse("routes:my_routes"))

    def test_rename_duplicate_is_rejected_but_other_users_name_is_allowed(self):
        second = SavedRoute.objects.create(
            user=self.user,
            name="Second",
            pickup_zone=self.pickup,
            dropoff_zone=self.dropoff,
        )
        url = self.route_url("rename_saved_route")
        page = self.client.post(url, {"name": " Second "})
        self.assertContains(page, "already have a saved route")
        self.route.refresh_from_db()
        self.assertEqual(self.route.name, "Commute")
        page = self.client.post(url, {"name": self.private_route.name})
        self.assertRedirects(page, reverse("routes:my_routes"))
        self.assertTrue(SavedRoute.objects.filter(pk=second.pk).exists())

    def test_delete_requires_confirmation_page_then_removes_only_that_route(self):
        url = self.route_url("delete_saved_route")
        page = self.client.get(url)
        self.assertContains(page, "Delete")
        self.assertContains(page, "Commute")
        self.assertContains(page, "csrfmiddlewaretoken")
        self.assertTrue(SavedRoute.objects.filter(pk=self.route.pk).exists())
        response = self.client.post(url)
        self.assertRedirects(response, reverse("routes:my_routes"))
        self.assertFalse(SavedRoute.objects.filter(pk=self.route.pk).exists())
        self.assertTrue(SavedRoute.objects.filter(pk=self.private_route.pk).exists())
        self.assertNotContains(self.client.get(reverse("routes:my_routes")), "Commute")

    def test_delete_and_rename_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(
            client.post(
                self.route_url("rename_saved_route"), {"name": "New"}
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(self.route_url("delete_saved_route")).status_code, 403
        )
        self.assertTrue(SavedRoute.objects.filter(pk=self.route.pk).exists())
