"""
US9: Use Without an Account (#11)

Verify that riders can access TaxiScope's map and trip information
without creating an account or logging in.
"""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from zones.models import Zone


class AnonymousAccessTests(TestCase):
    """Test that TaxiScope's public features work without authentication."""

    @classmethod
    def setUpTestData(cls):
        cls.zone = Zone.objects.create(
            zone_id=1,
            name="Newark Airport",
            borough="EWR",
        )

    def test_map_accessible_without_login(self):
        response = self.client.get(reverse("zones:map"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "zones/map.html")

    def test_zones_api_accessible_without_login(self):
        response = self.client.get(
            reverse("zones:zones_api"),
            {"day": 0, "hour": 12},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "FeatureCollection")

    def test_heatmap_accessible_without_login(self):
        response = self.client.get(
            reverse("zones:heatmap_api", args=[self.zone.zone_id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["zone_id"], self.zone.zone_id)

    @patch("zones.views.unknown_zone_ids", return_value=False)
    @patch("zones.views.route_stats", return_value={"enough_data": False})
    def test_routes_accessible_without_login(self, mock_stats, mock_unknown):
        response = self.client.get(
            reverse("zones:routes_api"),
            {"from": self.zone.zone_id, "day": 0, "hour": 12},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("enough_data", response.json())

    @patch("zones.views.unknown_zone_ids", return_value=False)
    @patch("zones.views.route_windows", return_value={"enough_data": False})
    def test_route_windows_accessible_without_login(
        self, mock_windows, mock_unknown
    ):
        response = self.client.get(
            reverse("zones:route_windows_api"),
            {"from": self.zone.zone_id, "day": 0},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("enough_data", response.json())