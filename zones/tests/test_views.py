from django.test import TestCase
from django.urls import reverse


class MapViewTests(TestCase):
    def test_map_page_returns_200_with_map_container(self):
        response = self.client.get(reverse("zones:map"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<div id="map">')
