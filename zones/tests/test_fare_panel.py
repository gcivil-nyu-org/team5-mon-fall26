"""US5 #7: View Fare Range, and US6 #8: View Trip Duration — template and
static file tests. Both lines are written by fare.js from the same
/api/routes response, so they are tested together here."""

from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse


STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "zones"


class FarePanelTemplateTests(TestCase):
    """The shared summary has fare and duration values and loads fare.js."""

    def setUp(self):
        self.response = self.client.get(reverse("zones:map"))

    def test_fare_line_is_labeled_fare_before_tip(self):
        self.assertContains(self.response, "Fare before tip (min / avg / max)")
        self.assertContains(self.response, 'id="fare-range"')

    def test_summary_shows_route_and_time_context(self):
        self.assertContains(self.response, 'id="summary-route"')
        self.assertContains(self.response, 'id="summary-time"')

    def test_duration_is_in_the_summary(self):
        self.assertContains(
            self.response,
            '<div><dt>Typical trip duration</dt><dd id="trip-duration">—</dd></div>',
            html=True,
        )

    def test_fare_js_loaded_after_filters_js(self):
        html = self.response.content.decode()
        self.assertIn("zones/js/fare.js", html)
        self.assertLess(html.index("zones/js/filters.js"), html.index("zones/js/fare.js"))


class FareJsTests(SimpleTestCase):
    """fare.js reads /api/routes and keeps only the newest response. US6 #8:
    it writes the duration line from the same response as the fare line."""

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

    def test_writes_duration_line(self):
        self.assertIn("trip-duration", self.js)
        self.assertIn("avg_duration_min", self.js)

    def test_duration_uses_same_enough_data_flag_as_fare(self):
        # Both lines are written inside the same `data.enough_data` branch,
        # so they are never computed from different responses.
        then_body = self.js.split(".then(data => {", 1)[1]
        enough_data_branch = then_body.split("data.enough_data")[1]
        self.assertIn("fareRange.textContent", enough_data_branch[:400])
        self.assertIn("tripDuration.textContent", enough_data_branch[:400])

    def test_duration_guarded_against_stale_responses(self):
        # The same sequence guard that protects the fare line also covers
        # the line(s) that write tripDuration.
        guard, _, rest = self.js.partition("if (sequence !== fareSequence) return;")
        self.assertIn("tripDuration", rest.split(".catch", 1)[0])


class FiltersJsFareTests(SimpleTestCase):
    """filters.js no longer writes the fare line or the duration line (US6
    #8): both now come from fare.js's single /api/routes response."""

    def setUp(self):
        self.js = (STATIC_DIR / "js" / "filters.js").read_text()

    def test_does_not_write_fare_line(self):
        self.assertNotIn("fareRange", self.js)
        self.assertNotIn("fare-range", self.js)

    def test_does_not_write_duration_line(self):
        self.assertNotIn("tripDuration", self.js)
        self.assertNotIn("trip-duration", self.js)
        self.assertNotIn("updatePickupStats", self.js)

    def test_dispatches_time_changed(self):
        self.assertIn("taxiscope:time-changed", self.js)
