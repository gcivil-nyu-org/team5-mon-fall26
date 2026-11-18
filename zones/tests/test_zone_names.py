"""US42 #116: a zone renamed in the admin shows its new name and borough on
the map, the compare page, plans and ride posts, and running the imports
again does not undo the edit."""

from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from rides.models import RidePost
from routes.models import TripPlan
from zones.importer.load import upsert_zones
from zones.importer.read import read_zone_lookup
from zones.models import Zone
from zones.tests.test_import_history import ImportFiles

NEW_NAME = "JFK International Airport"
NEW_BOROUGH = "Brooklyn"  # not true, but easy to spot on every page


def rename_in_admin(client, zone_id=132, name=NEW_NAME, borough=NEW_BOROUGH):
    return client.post(
        reverse("admin:zones_zone_change", args=[zone_id]),
        {"name": name, "borough": borough},
    )


class RenamedZoneShowsEverywhereTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        upsert_zones(read_zone_lookup())
        User = get_user_model()
        cls.staff = User.objects.create_superuser(
            "staff@example.com", "staff@example.com", "taxi-route-7319"
        )
        cls.rider = User.objects.create_user(
            "rider@example.com", "rider@example.com", "taxi-route-7319"
        )
        Profile.objects.create(user=cls.rider, display_name="Early Bird")
        midtown = Zone.objects.get(zone_id=161)
        jfk = Zone.objects.get(zone_id=132)
        cls.plan = TripPlan.objects.create(
            user=cls.rider,
            name="Flight home",
            pickup_zone=midtown,
            dropoff_zone=jfk,
            mode=TripPlan.ARRIVE_BY,
            day_of_week=0,
            time=time(9, 0),
        )
        cls.post = RidePost.objects.create(
            owner=cls.rider,
            pickup_zone=midtown,
            dropoff_zone=jfk,
            departure_at=timezone.now() + timedelta(days=1),
            seats=2,
        )

    def setUp(self):
        self.client.force_login(self.staff)
        rename_in_admin(self.client)
        self.client.force_login(self.rider)

    def test_the_map_shows_the_new_name(self):
        response = self.client.get(reverse("zones:zones_api"), {"day": 0, "hour": 8})

        jfk = next(
            feature["properties"]
            for feature in response.json()["features"]
            if feature["properties"]["zone_id"] == 132
        )
        self.assertEqual((jfk["name"], jfk["borough"]), (NEW_NAME, NEW_BOROUGH))

    def test_the_compare_page_lists_the_new_name(self):
        response = self.client.get(reverse("zones:compare"))

        self.assertContains(response, NEW_NAME)
        self.assertNotContains(response, ">JFK Airport<")

    def test_plans_show_the_new_name(self):
        response = self.client.get(reverse("routes:my_plans"))

        self.assertContains(response, f"Midtown Center → {NEW_NAME}")

    def test_ride_posts_show_the_new_name_and_borough(self):
        detail = self.client.get(reverse("rides:ride_detail", args=[self.post.pk]))
        mine = self.client.get(reverse("rides:my_rides"))

        self.assertContains(detail, f"{NEW_NAME} ({NEW_BOROUGH})")
        self.assertContains(mine, NEW_NAME)


class ImportKeepsAdminEditsTests(ImportFiles, TestCase):
    def setUp(self):
        super().setUp()
        self.taxi("2026-03")  # loads the 265 zones from the TLC lookup
        staff = get_user_model().objects.create_superuser(
            "staff@example.com", "staff@example.com", "taxi-route-7319"
        )
        self.client.force_login(staff)

    def assert_zone(self, zone_id, name, borough):
        zone = Zone.objects.get(zone_id=zone_id)
        self.assertEqual((zone.name, zone.borough), (name, borough))
        return zone

    def test_import_trips_does_not_undo_an_admin_edit(self):
        rename_in_admin(self.client)

        output = self.taxi("2026-03")

        zone = self.assert_zone(132, NEW_NAME, NEW_BOROUGH)
        self.assertTrue(zone.edited_by_admin)
        self.assertEqual(zone.edited_by, "staff@example.com")
        self.assertIn("Zones loaded: 265.", output)

    def test_import_rideshare_does_not_undo_an_admin_edit(self):
        rename_in_admin(self.client)

        self.rideshare("2026-03")

        self.assert_zone(132, NEW_NAME, NEW_BOROUGH)

    def test_zones_not_edited_in_the_admin_still_follow_the_lookup(self):
        rename_in_admin(self.client)
        Zone.objects.filter(zone_id=4).update(name="Old name", borough="Bronx")

        self.taxi("2026-03")

        self.assert_zone(4, "Alphabet City", "Manhattan")
        self.assert_zone(132, NEW_NAME, NEW_BOROUGH)
        self.assertEqual(Zone.objects.count(), 265)

    def test_an_unticked_zone_gets_the_tlc_name_back_at_the_next_import(self):
        rename_in_admin(self.client)
        # Saved again with the same name and borough and "edited in the
        # admin" unticked (an unticked checkbox is not posted).
        self.client.post(
            reverse("admin:zones_zone_change", args=[132]),
            {"name": NEW_NAME, "borough": NEW_BOROUGH},
        )
        self.assertFalse(Zone.objects.get(zone_id=132).edited_by_admin)

        self.taxi("2026-03")

        self.assert_zone(132, "JFK Airport", "Queens")
