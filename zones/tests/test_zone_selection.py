"""US2 #4: Select Trip Zones — template and static file tests."""

import re
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse


STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "zones"


class ZoneSelectionTemplateTests(TestCase):
    """The map page includes the pickup/dropoff selection UI."""

    def setUp(self):
        self.response = self.client.get(reverse("zones:map"))

    def test_pickup_zone_element_present(self):
        self.assertContains(self.response, 'id="pickup-zone"')

    def test_dropoff_zone_element_present(self):
        self.assertContains(self.response, 'id="dropoff-zone"')

    def test_pickup_default_text(self):
        self.assertContains(self.response, "Click a zone")

    def test_clear_pickup_button_present(self):
        self.assertContains(self.response, 'id="clear-pickup"')

    def test_clear_dropoff_button_present(self):
        self.assertContains(self.response, 'id="clear-dropoff"')

    def test_clear_selection_button_present(self):
        self.assertContains(self.response, 'id="clear-selection"')

    def test_clear_buttons_hidden_by_default(self):
        content = self.response.content.decode()
        self.assertIn('id="clear-pickup"', content)
        clear_pickup_match = re.search(
            r'<button[^>]*id="clear-pickup"[^>]*>', content
        )
        self.assertIsNotNone(clear_pickup_match)
        self.assertIn("hidden", clear_pickup_match.group(0))

    def test_clear_selection_hidden_by_default(self):
        content = self.response.content.decode()
        clear_sel_match = re.search(
            r'<button[^>]*id="clear-selection"[^>]*>', content
        )
        self.assertIsNotNone(clear_sel_match)
        self.assertIn("hidden", clear_sel_match.group(0))

    def test_selection_panel_has_aria_live(self):
        self.assertContains(self.response, 'aria-live="polite"')

    def test_trip_summary_is_inside_selection_panel(self):
        html = self.response.content.decode()
        selection = html[html.index('<aside class="zone-selection"'):]
        selection = selection[:selection.index('</aside>')]
        self.assertIn('id="summary-toggle"', selection)
        self.assertIn('id="summary-panel"', selection)
        for field in ('fare-range', 'trip-duration', 'best-fare',
                      'best-duration', 'worst-fare', 'worst-duration'):
            self.assertIn(f'id="{field}"', selection)
        for label in ('Cheapest:', 'Fastest:', 'Most expensive:', 'Slowest:'):
            self.assertIn(label, selection)

    def test_existing_components_write_to_one_summary(self):
        html = self.response.content.decode()
        for field in ('fare-range', 'trip-duration', 'best-fare',
                      'best-duration', 'worst-fare', 'worst-duration'):
            self.assertEqual(html.count(f'id="{field}"'), 1)
        self.assertIn('zones/js/fare.js', html)
        self.assertIn('zones/js/windows.js', html)


class FiltersJsSyntaxTests(SimpleTestCase):
    """The filters.js file is syntactically valid and has the selection logic."""

    def setUp(self):
        self.js = (STATIC_DIR / "js" / "filters.js").read_text()

    def test_pickup_zone_id_variable(self):
        self.assertIn("pickupZoneId", self.js)

    def test_dropoff_zone_id_variable(self):
        self.assertIn("dropoffZoneId", self.js)

    def test_select_zone_function(self):
        self.assertIn("function selectZone", self.js)

    def test_clear_pickup_function(self):
        self.assertIn("function clearPickup", self.js)

    def test_clear_dropoff_function(self):
        self.assertIn("function clearDropoff", self.js)

    def test_pickup_color_defined(self):
        self.assertIn("PICKUP_COLOR", self.js)

    def test_dropoff_color_defined(self):
        self.assertIn("DROPOFF_COLOR", self.js)

    def test_style_zone_checks_pickup_and_dropoff(self):
        self.assertIn("isPickup", self.js)
        self.assertIn("isDropoff", self.js)

    def test_zones_selected_event_dispatched(self):
        self.assertIn("taxiscope:zones-selected", self.js)

    def test_click_handler_calls_select_zone(self):
        self.assertIn("selectZone(zoneId)", self.js)


class SelectionCssTests(SimpleTestCase):
    """The CSS has the zone selection styles."""

    def setUp(self):
        self.css = (STATIC_DIR / "css" / "map.css").read_text()

    def test_zone_selection_class(self):
        self.assertIn(".zone-selection", self.css)

    def test_pickup_label_color(self):
        self.assertIn(".pickup-label", self.css)

    def test_dropoff_label_color(self):
        self.assertIn(".dropoff-label", self.css)

    def test_clear_btn_class(self):
        self.assertIn(".clear-btn", self.css)

    def test_clear_all_btn_class(self):
        self.assertIn(".clear-all-btn", self.css)
