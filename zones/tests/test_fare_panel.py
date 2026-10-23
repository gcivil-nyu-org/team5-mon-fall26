"""US5 #7: View Fare Range — template and static file tests."""

from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse


STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "zones"


class FarePanelTemplateTests(TestCase):
    """The selection panel has the fare line and loads fare.js."""

    def setUp(self):
        self.response = self.client.get(reverse("zones:map"))

    def test_fare_line_is_labeled_fare_before_tip(self):
        self.assertContains(self.response, "Fare before tip:")
        self.assertContains(self.response, 'id="fare-range"')

    def test_fare_scope_element_present(self):
        self.assertContains(self.response, 'id="fare-scope"')

    def test_duration_line_unchanged(self):
        self.assertContains(
            self.response,
            '<p>Average trip duration: <strong id="trip-duration">—</strong></p>',
            html=True,
        )

    def test_fare_js_loaded_after_filters_js(self):
        html = self.response.content.decode()
        self.assertIn("zones/js/fare.js", html)
        self.assertLess(html.index("zones/js/filters.js"), html.index("zones/js/fare.js"))


class FareJsTests(SimpleTestCase):
    """fare.js reads /api/routes and keeps only the newest response."""

    def setUp(self):
        self.js = (STATIC_DIR / "js" / "fare.js").read_text()

    def test_calls_routes_api(self):
        self.assertIn("/api/routes", self.js)

    def test_shows_not_enough_data(self):
        self.assertIn("'Not enough data'", self.js)

    def test_listens_to_selection_time_and_map_events(self):
        self.assertIn("taxiscope:zones-selected", self.js)
        self.assertIn("taxiscope:time-changed", self.js)
        self.assertIn("taxiscope:map-ready", self.js)

    def test_ignores_older_responses(self):
        self.assertIn("fareSequence", self.js)

    def test_writes_text_not_html(self):
        self.assertNotIn("innerHTML", self.js)


class FiltersJsFareTests(SimpleTestCase):
    """filters.js no longer writes the fare line but still writes duration."""

    def setUp(self):
        self.js = (STATIC_DIR / "js" / "filters.js").read_text()

    def test_does_not_write_fare_line(self):
        self.assertNotIn("fareRange", self.js)
        self.assertNotIn("fare-range", self.js)

    def test_still_writes_duration_line(self):
        self.assertIn("tripDuration.textContent", self.js)

    def test_dispatches_time_changed(self):
        self.assertIn("taxiscope:time-changed", self.js)
