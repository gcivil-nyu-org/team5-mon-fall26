"""US39 #113: zones are in the admin, read-only until US42 makes the names
editable."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from zones.admin import ReadOnlyModelAdmin, ZoneAdmin
from zones.models import Zone


class ZoneAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_superuser(
            "staff@example.com", "staff@example.com", "taxi-route-7319"
        )
        cls.zone = Zone.objects.create(
            zone_id=132, name="JFK Airport", borough="Queens"
        )
        Zone.objects.create(zone_id=4, name="Alphabet City", borough="Manhattan")

    def setUp(self):
        self.client.force_login(self.staff)

    def test_zone_is_registered_read_only(self):
        model_admin = admin.site._registry[Zone]

        self.assertIsInstance(model_admin, ZoneAdmin)
        self.assertIsInstance(model_admin, ReadOnlyModelAdmin)

    def test_staff_can_list_search_and_filter_zones(self):
        url = reverse("admin:zones_zone_changelist")

        everything = self.client.get(url)
        searched = self.client.get(url, {"q": "JFK"})
        queens = self.client.get(url, {"borough": "Queens"})

        self.assertContains(everything, "JFK Airport")
        self.assertContains(everything, "Alphabet City")
        self.assertEqual(searched.context["cl"].result_count, 1)
        self.assertEqual(queens.context["cl"].result_count, 1)

    def test_staff_can_view_a_zone_but_not_change_it(self):
        url = reverse("admin:zones_zone_change", args=[132])

        page = self.client.get(url)
        self.client.post(url, {"name": "Renamed", "borough": "Bronx"})

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "JFK Airport")
        self.assertNotContains(page, 'name="name"')
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.name, "JFK Airport")

    def test_zones_cannot_be_added_or_deleted(self):
        add = self.client.get(reverse("admin:zones_zone_add"))
        delete = self.client.post(
            reverse("admin:zones_zone_delete", args=[132]), {"post": "yes"}
        )
        changelist = self.client.get(reverse("admin:zones_zone_changelist"))

        self.assertEqual(add.status_code, 403)
        self.assertEqual(delete.status_code, 403)
        self.assertTrue(Zone.objects.filter(zone_id=132).exists())
        self.assertNotContains(changelist, "delete_selected")
