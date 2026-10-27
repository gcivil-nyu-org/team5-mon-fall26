from django.test import TestCase
from django.urls import reverse

from zones.models import Zone, ZoneHourStats


class MapViewTests(TestCase):
    def test_map_page_returns_200_with_map_container(self):
        response = self.client.get(reverse("zones:map"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<div id="map">')

    def test_map_page_has_pickup_and_dropoff_elements(self):
        response = self.client.get(reverse("zones:map"))

        self.assertContains(response, 'id="pickup-zone"')
        self.assertContains(response, 'id="dropoff-zone"')

    def test_map_page_has_clear_buttons(self):
        response = self.client.get(reverse("zones:map"))

        self.assertContains(response, 'id="clear-pickup"')
        self.assertContains(response, 'id="clear-dropoff"')
        self.assertContains(response, 'id="clear-selection"')

    def test_map_page_loads_filters_js(self):
        response = self.client.get(reverse("zones:map"))

        self.assertContains(response, "filters.js")


class HeatmapAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.zone = Zone.objects.create(zone_id=1, name="Test Zone", borough="Manhattan")
        # Create 7x24 stats, with some missing cells
        for day in range(7):
            for hour in range(24):
                # Skip some cells to test "no data" handling
                if day == 0 and hour < 6:
                    continue
                if day == 6 and hour > 20:
                    continue
                ZoneHourStats.objects.create(
                    zone=cls.zone,
                    day_of_week=day,
                    hour=hour,
                    trip_count=10 + day * hour,
                    avg_duration_min=15.5 + hour * 0.5,
                    fare_min=10.00,
                    fare_avg=25.50,
                    fare_max=50.00,
                )

    def test_heatmap_returns_7x24_grid(self):
        response = self.client.get(
            reverse("zones:heatmap_api", args=[self.zone.zone_id])
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["zone_id"], 1)
        self.assertIn("heatmap", data)
        self.assertEqual(len(data["heatmap"]), 7)  # 7 days
        for day_data in data["heatmap"]:
            self.assertEqual(len(day_data), 24)  # 24 hours

    def test_heatmap_contains_trip_count_and_duration(self):
        response = self.client.get(
            reverse("zones:heatmap_api", args=[self.zone.zone_id])
        )

        data = response.json()
        # Check a cell that exists (Monday hour 12)
        monday_noon = data["heatmap"][0][12]
        self.assertIn("trip_count", monday_noon)
        self.assertIn("avg_duration_min", monday_noon)
        self.assertIsNotNone(monday_noon["trip_count"])
        self.assertIsNotNone(monday_noon["avg_duration_min"])

    def test_heatmap_marks_missing_data_as_null(self):
        response = self.client.get(
            reverse("zones:heatmap_api", args=[self.zone.zone_id])
        )

        data = response.json()
        # Check cells we deliberately skipped (Monday 0-5)
        monday_early = data["heatmap"][0][0]
        self.assertIsNone(monday_early["trip_count"])
        self.assertIsNone(monday_early["avg_duration_min"])

    def test_heatmap_returns_404_for_nonexistent_zone(self):
        response = self.client.get(reverse("zones:heatmap_api", args=[9999]))

        self.assertEqual(response.status_code, 404)
