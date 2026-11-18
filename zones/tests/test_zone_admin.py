"""US42 #116 (zones were read-only in US39 #113): staff correct a zone's
name and borough in the admin; the zone id can't change and zones can't be
added or deleted; the list shows which zones were edited, by whom and
when. (Guests and riders are refused on every admin URL by
accounts/tests/test_admin_access.py.)"""

from datetime import datetime, timezone
from unittest import mock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from zones.admin import BOROUGHS, ReadOnlyModelAdmin, ZoneAdmin
from zones.models import Zone

CHANGELIST = reverse("admin:zones_zone_changelist")
NOW = datetime(2026, 11, 18, 15, 30, tzinfo=timezone.utc)


def change_url(zone_id):
    return reverse("admin:zones_zone_change", args=[zone_id])


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
        patcher = mock.patch("zones.admin.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, zone_id=132, **data):
        values = {"name": "JFK Airport", "borough": "Queens", **data}
        if values.pop("edited_by_admin", False):
            values["edited_by_admin"] = "on"
        return self.client.post(change_url(zone_id), values)

    def test_zone_admin_is_editable(self):
        model_admin = admin.site._registry[Zone]

        self.assertIsInstance(model_admin, ZoneAdmin)
        self.assertNotIsInstance(model_admin, ReadOnlyModelAdmin)

    def test_staff_can_list_search_and_filter_zones(self):
        everything = self.client.get(CHANGELIST)
        searched = self.client.get(CHANGELIST, {"q": "JFK"})
        queens = self.client.get(CHANGELIST, {"borough": "Queens"})

        self.assertContains(everything, "JFK Airport")
        self.assertContains(everything, "Alphabet City")
        self.assertEqual(searched.context["cl"].result_count, 1)
        self.assertEqual(queens.context["cl"].result_count, 1)

    def test_the_change_page_edits_name_and_borough_only(self):
        page = self.client.get(change_url(132))

        self.assertContains(page, 'name="name"')
        self.assertContains(page, 'name="borough"')
        self.assertNotContains(page, 'name="zone_id"')
        self.assertNotContains(page, 'name="edited_by"')
        self.assertNotContains(page, 'name="edited_at"')
        for borough in BOROUGHS:
            self.assertContains(page, f'<option value="{borough}"')

    def test_staff_rename_a_zone(self):
        response = self.save(name="JFK International Airport", borough="Queens")

        self.assertRedirects(response, CHANGELIST)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.name, "JFK International Airport")
        self.assertTrue(self.zone.edited_by_admin)
        self.assertEqual(self.zone.edited_by, "staff@example.com")
        self.assertEqual(self.zone.edited_at, NOW)

    def test_staff_change_a_borough(self):
        self.save(zone_id=4, name="Alphabet City", borough="Brooklyn")

        zone = Zone.objects.get(zone_id=4)
        self.assertEqual(zone.borough, "Brooklyn")
        self.assertTrue(zone.edited_by_admin)

    def test_the_name_is_trimmed_and_cannot_be_blank(self):
        self.save(name="  JFK   Airport  Terminal ")
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.name, "JFK Airport Terminal")

        response = self.save(name="   ")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.name, "JFK Airport Terminal")

    def test_the_borough_must_be_a_tlc_borough(self):
        response = self.save(borough="Manhatan")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice.")
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.borough, "Queens")
        self.assertFalse(self.zone.edited_by_admin)

    def test_saving_without_a_change_records_nothing(self):
        self.save()

        self.zone.refresh_from_db()
        self.assertFalse(self.zone.edited_by_admin)
        self.assertEqual((self.zone.edited_by, self.zone.edited_at), ("", None))

    def test_unticking_hands_the_zone_back_to_the_import(self):
        self.save(name="JFK International Airport")

        self.save(name="JFK International Airport", edited_by_admin=False)

        self.zone.refresh_from_db()
        self.assertFalse(self.zone.edited_by_admin)
        self.assertEqual(self.zone.name, "JFK International Airport")
        self.assertEqual(self.zone.edited_by, "staff@example.com")

    def test_a_rename_always_marks_the_zone_edited(self):
        self.save(name="JFK International Airport", edited_by_admin=False)

        self.zone.refresh_from_db()
        self.assertTrue(self.zone.edited_by_admin)

    def test_the_list_shows_who_edited_which_zone_and_when(self):
        self.save(name="JFK International Airport")

        everything = self.client.get(CHANGELIST)
        edited = self.client.get(CHANGELIST, {"edited_by_admin__exact": "1"})

        self.assertContains(everything, "staff@example.com")
        self.assertContains(everything, "Nov. 18, 2026, 3:30 p.m.")
        self.assertEqual(edited.context["cl"].result_count, 1)
        self.assertContains(edited, "JFK International Airport")

    def test_the_zone_id_cannot_be_changed(self):
        self.client.post(
            change_url(132), {"zone_id": 999, "name": "JFK", "borough": "Queens"}
        )

        self.assertTrue(Zone.objects.filter(zone_id=132).exists())
        self.assertFalse(Zone.objects.filter(zone_id=999).exists())

    def test_zones_cannot_be_added_or_deleted(self):
        add = self.client.get(reverse("admin:zones_zone_add"))
        delete = self.client.post(
            reverse("admin:zones_zone_delete", args=[132]), {"post": "yes"}
        )
        changelist = self.client.get(CHANGELIST)

        self.assertEqual(add.status_code, 403)
        self.assertEqual(delete.status_code, 403)
        self.assertTrue(Zone.objects.filter(zone_id=132).exists())
        self.assertNotContains(changelist, "delete_selected")
        self.assertNotContains(changelist, reverse("admin:zones_zone_add"))
