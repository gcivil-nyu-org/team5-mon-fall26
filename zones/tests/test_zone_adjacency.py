"""US43 #117: Manage Zone Adjacency. Staff add a missing pair of
neighbouring zones or remove a wrong one, with a reason. The change applies
both ways and straight away to cheaper-pickup suggestions (US19) and ride
matching (US32); deleting an override puts the pair back to what
zone_neighbors.json says; a zone can't be paired with itself; rebuilding the
file (US18 script) keeps the overrides. (Guests and riders are refused on
every admin URL by accounts/tests/test_admin_access.py.)"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from rides.search import _with_neighbors
from routes.planning import cheaper_nearby
from zones import stats
from zones.models import Zone, ZoneAdjacencyOverride
from zones.stats import file_zone_neighbors, load_zone_neighbors, neighbor_sources

# From zone_neighbors.json: Midtown Center (161) borders Midtown East (162);
# Upper East Side South (237) borders neither JFK (132) nor Midtown Center.
MIDTOWN_CENTER, MIDTOWN_EAST, JFK, UES_SOUTH = 161, 162, 132, 237
NOW = datetime(2026, 11, 18, 15, 30, tzinfo=timezone.utc)
ADD, REMOVE = ZoneAdjacencyOverride.ADD, ZoneAdjacencyOverride.REMOVE
CHANGELIST = reverse("admin:zones_zoneadjacencyoverride_changelist")
ADD_URL = reverse("admin:zones_zoneadjacencyoverride_add")


def make_zones():
    for zone_id, name in (
        (MIDTOWN_CENTER, "Midtown Center"),
        (MIDTOWN_EAST, "Midtown East"),
        (JFK, "JFK Airport"),
        (UES_SOUTH, "Upper East Side South"),
    ):
        Zone.objects.create(zone_id=zone_id, name=name, borough="Manhattan")


def override(zone_a, zone_b, action, reason="Checked on the map"):
    return ZoneAdjacencyOverride.objects.create(
        zone_a_id=zone_a, zone_b_id=zone_b, action=action, reason=reason
    )


class FileAssumptionTests(TestCase):
    """The pairs these tests use, as the committed file has them."""

    def test_the_file_has_the_pairs_these_tests_assume(self):
        neighbors = file_zone_neighbors()

        self.assertIn(MIDTOWN_EAST, neighbors[MIDTOWN_CENTER])
        self.assertNotIn(JFK, neighbors[UES_SOUTH])
        self.assertNotIn(UES_SOUTH, neighbors[JFK])


class CombinedNeighborsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_zones()

    def test_without_overrides_it_is_the_file(self):
        self.assertIs(load_zone_neighbors(), file_zone_neighbors())

    def test_an_added_pair_applies_both_ways(self):
        override(JFK, UES_SOUTH, ADD)

        neighbors = load_zone_neighbors()

        self.assertIn(UES_SOUTH, neighbors[JFK])
        self.assertIn(JFK, neighbors[UES_SOUTH])
        self.assertEqual(neighbors[JFK], sorted(neighbors[JFK]))

    def test_a_removed_pair_applies_both_ways(self):
        override(MIDTOWN_CENTER, MIDTOWN_EAST, REMOVE)

        neighbors = load_zone_neighbors()

        self.assertNotIn(MIDTOWN_EAST, neighbors[MIDTOWN_CENTER])
        self.assertNotIn(MIDTOWN_CENTER, neighbors[MIDTOWN_EAST])
        self.assertIn(163, neighbors[MIDTOWN_CENTER])  # other neighbours stay

    def test_overrides_do_not_change_the_cached_file(self):
        override(JFK, UES_SOUTH, ADD)
        override(MIDTOWN_CENTER, MIDTOWN_EAST, REMOVE)

        load_zone_neighbors()

        self.assertNotIn(UES_SOUTH, file_zone_neighbors()[JFK])
        self.assertIn(MIDTOWN_EAST, file_zone_neighbors()[MIDTOWN_CENTER])

    def test_deleting_an_override_puts_the_pair_back_to_the_file(self):
        added = override(JFK, UES_SOUTH, ADD)
        removed = override(MIDTOWN_CENTER, MIDTOWN_EAST, REMOVE)

        added.delete()
        removed.delete()

        self.assertEqual(load_zone_neighbors(), file_zone_neighbors())

    def test_an_added_zone_missing_from_the_file_gets_an_entry(self):
        with mock.patch.object(stats, "file_zone_neighbors", return_value={JFK: []}):
            override(JFK, UES_SOUTH, ADD)

            self.assertEqual(
                load_zone_neighbors(), {JFK: [UES_SOUTH], UES_SOUTH: [JFK]}
            )


class RebuiltFileTests(TestCase):
    """Rebuilding zone_neighbors.json with scripts/build_zone_neighbors.py
    writes a new file; the overrides are in the database, so they still
    apply to it."""

    @classmethod
    def setUpTestData(cls):
        make_zones()

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "zone_neighbors.json"
        file_zone_neighbors.cache_clear()
        self.addCleanup(file_zone_neighbors.cache_clear)
        patcher = mock.patch.object(stats, "NEIGHBORS_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, neighbors):
        self.path.write_text(json.dumps({str(k): v for k, v in neighbors.items()}))
        file_zone_neighbors.cache_clear()

    def test_overrides_still_apply_after_a_rebuild(self):
        self.write(
            {
                JFK: [2],
                2: [JFK],
                MIDTOWN_CENTER: [MIDTOWN_EAST],
                MIDTOWN_EAST: [MIDTOWN_CENTER],
                UES_SOUTH: [],
            }
        )
        override(JFK, UES_SOUTH, ADD)
        override(MIDTOWN_CENTER, MIDTOWN_EAST, REMOVE)

        self.write(
            {
                JFK: [2, 3],
                2: [JFK],
                3: [JFK],
                MIDTOWN_CENTER: [MIDTOWN_EAST],
                MIDTOWN_EAST: [MIDTOWN_CENTER],
                UES_SOUTH: [],
            }
        )
        neighbors = load_zone_neighbors()

        self.assertEqual(neighbors[JFK], [2, 3, UES_SOUTH])
        self.assertEqual(neighbors[UES_SOUTH], [JFK])
        self.assertEqual(neighbors[MIDTOWN_CENTER], [])
        self.assertEqual(ZoneAdjacencyOverride.objects.count(), 2)


class AppliesStraightAwayTests(TestCase):
    """US19 and US32 read the combined list on every request, so a change
    applies without a restart."""

    @classmethod
    def setUpTestData(cls):
        make_zones()

    def test_ride_matching_uses_an_added_pair(self):
        self.assertNotIn(UES_SOUTH, _with_neighbors(JFK))

        override(JFK, UES_SOUTH, ADD)

        self.assertIn(UES_SOUTH, _with_neighbors(JFK))
        self.assertIn(JFK, _with_neighbors(UES_SOUTH))

    def test_ride_matching_drops_a_removed_pair(self):
        override(MIDTOWN_CENTER, MIDTOWN_EAST, REMOVE)

        self.assertNotIn(MIDTOWN_EAST, _with_neighbors(MIDTOWN_CENTER))

    def test_cheaper_pickup_considers_an_added_pair(self):
        before = cheaper_nearby(UES_SOUTH, MIDTOWN_CENTER, 2, 18)["neighbor_count"]

        override(JFK, UES_SOUTH, ADD)
        after = cheaper_nearby(UES_SOUTH, MIDTOWN_CENTER, 2, 18)["neighbor_count"]

        self.assertEqual(after, before + 1)

    def test_cheaper_pickup_drops_a_removed_pair(self):
        before = cheaper_nearby(MIDTOWN_CENTER, JFK, 2, 18)["neighbor_count"]

        override(MIDTOWN_CENTER, MIDTOWN_EAST, REMOVE)
        after = cheaper_nearby(MIDTOWN_CENTER, JFK, 2, 18)["neighbor_count"]

        self.assertEqual(after, before - 1)


class OverrideRulesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_zones()

    def checked(self, zone_a, zone_b, action):
        row = ZoneAdjacencyOverride(
            zone_a_id=zone_a, zone_b_id=zone_b, action=action, reason="Checked"
        )
        row.full_clean()
        return row

    def assert_refused(self, field, message, *args):
        with self.assertRaises(ValidationError) as caught:
            self.checked(*args)
        self.assertIn(message, " ".join(caught.exception.message_dict[field]))

    def test_a_zone_cannot_be_paired_with_itself(self):
        self.assert_refused("zone_b", "can't be its own neighbour", JFK, JFK, ADD)

    def test_cannot_add_a_pair_the_file_already_has(self):
        self.assert_refused(
            "action", "already neighbours", MIDTOWN_EAST, MIDTOWN_CENTER, ADD
        )

    def test_cannot_remove_a_pair_the_file_does_not_have(self):
        self.assert_refused("action", "nothing to remove", JFK, UES_SOUTH, REMOVE)

    def test_a_pair_is_stored_lower_zone_first(self):
        row = self.checked(UES_SOUTH, JFK, ADD)
        row.save()

        self.assertEqual((row.zone_a_id, row.zone_b_id), (JFK, UES_SOUTH))
        self.assertEqual(str(row), "add 132 ↔ 237")

    def test_save_also_puts_the_lower_zone_first(self):
        row = override(MIDTOWN_EAST, MIDTOWN_CENTER, REMOVE)

        self.assertEqual((row.zone_a_id, row.zone_b_id), (MIDTOWN_CENTER, MIDTOWN_EAST))
        self.assertEqual(str(row), "remove 161 ↔ 162")

    def test_one_override_per_pair_in_either_order(self):
        override(JFK, UES_SOUTH, ADD)

        self.assert_refused("__all__", "already has an override", UES_SOUTH, JFK, ADD)

    def test_the_database_refuses_a_pair_in_the_wrong_order(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ZoneAdjacencyOverride.objects.bulk_create(
                [
                    ZoneAdjacencyOverride(
                        zone_a_id=UES_SOUTH, zone_b_id=JFK, action=ADD, reason="x"
                    )
                ]
            )

    def test_an_incomplete_pair_is_left_to_the_required_field_check(self):
        row = ZoneAdjacencyOverride(zone_a_id=JFK, action=ADD, reason="x")

        with self.assertRaises(ValidationError) as caught:
            row.full_clean()

        self.assertIn("zone_b", caught.exception.message_dict)

    def test_neighbor_sources_marks_file_added_and_removed(self):
        override(JFK, MIDTOWN_CENTER, ADD)
        override(MIDTOWN_CENTER, MIDTOWN_EAST, REMOVE)

        sources = dict(neighbor_sources(MIDTOWN_CENTER))

        self.assertEqual(sources[JFK], "added")
        self.assertEqual(sources[MIDTOWN_EAST], "removed")
        self.assertEqual(sources[163], "file")
        self.assertEqual(neighbor_sources(1), [])


class OverrideAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_zones()
        cls.staff = get_user_model().objects.create_superuser(
            "staff@example.com", "staff@example.com", "taxi-route-7319"
        )

    def setUp(self):
        self.client.force_login(self.staff)
        patcher = mock.patch("zones.admin.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, url=ADD_URL, **data):
        values = {
            "zone_a": JFK,
            "zone_b": UES_SOUTH,
            "action": ADD,
            "reason": "Same terminal shuttle",
            **data,
        }
        return self.client.post(url, values)

    def test_staff_add_a_pair_with_a_reason_and_who_and_when_is_recorded(self):
        response = self.post()

        self.assertRedirects(response, CHANGELIST)
        row = ZoneAdjacencyOverride.objects.get()
        self.assertEqual(
            (row.zone_a_id, row.zone_b_id, row.action), (JFK, UES_SOUTH, ADD)
        )
        self.assertEqual(row.reason, "Same terminal shuttle")
        self.assertEqual((row.changed_by, row.changed_at), ("staff@example.com", NOW))
        self.assertIn(UES_SOUTH, load_zone_neighbors()[JFK])

    def test_staff_remove_a_wrong_pair(self):
        self.post(
            zone_a=MIDTOWN_EAST,
            zone_b=MIDTOWN_CENTER,
            action=REMOVE,
            reason="Separated by a highway",
        )

        self.assertNotIn(MIDTOWN_EAST, load_zone_neighbors()[MIDTOWN_CENTER])

    def test_the_reason_is_required(self):
        response = self.post(reason="")

        self.assertContains(response, "This field is required.")
        self.assertFalse(ZoneAdjacencyOverride.objects.exists())

    def test_a_self_pair_is_refused_with_a_message(self):
        response = self.post(zone_b=JFK)

        self.assertContains(response, "A zone can&#x27;t be its own neighbour.")
        self.assertFalse(ZoneAdjacencyOverride.objects.exists())

    def test_the_list_shows_each_override(self):
        override(JFK, UES_SOUTH, ADD, reason="Same terminal shuttle")

        response = self.client.get(CHANGELIST)

        self.assertContains(response, "add 132 ↔ 237")
        self.assertContains(response, "Same terminal shuttle")

    def test_staff_delete_an_override(self):
        row = override(JFK, UES_SOUTH, ADD)
        url = reverse("admin:zones_zoneadjacencyoverride_delete", args=[row.pk])

        self.client.post(url, {"post": "yes"})

        self.assertFalse(ZoneAdjacencyOverride.objects.exists())
        self.assertEqual(load_zone_neighbors(), file_zone_neighbors())

    def test_the_zone_page_shows_where_each_neighbour_comes_from(self):
        override(JFK, MIDTOWN_CENTER, ADD)
        override(MIDTOWN_CENTER, MIDTOWN_EAST, REMOVE)

        response = self.client.get(
            reverse("admin:zones_zone_change", args=[MIDTOWN_CENTER])
        )

        self.assertContains(response, "132 JFK Airport</span> (added in the admin)")
        self.assertContains(response, "<s>162 Midtown East</s> (removed in the admin)")
        self.assertContains(response, "163 Unknown zone</span> (from the file)")

    def test_a_zone_without_neighbours_says_none(self):
        Zone.objects.create(zone_id=1, name="Newark Airport", borough="EWR")

        response = self.client.get(reverse("admin:zones_zone_change", args=[1]))

        self.assertContains(response, "None")
