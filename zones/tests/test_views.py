from django.test import TestCase
from django.urls import reverse


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
