"""US7 #9: Find Best and Worst Travel Times — template and static file
tests for the best and worst times section."""

from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse


STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "zones"


class WindowsPanelTemplateTests(TestCase):
    """The shared summary has labeled best and worst rows."""

    def setUp(self):
        self.response = self.client.get(reverse("zones:map"))

    def test_rows_hidden_until_a_route_is_selected(self):
        html = self.response.content.decode()
        for row_id in ("best-row", "worst-row"):
            row = html[html.index(f'id="{row_id}"'):]
            self.assertIn("hidden", row[:row.index(">")])

    def test_best_and_worst_are_labeled(self):
        for text in ("Best", "Worst", "Cheapest", "Fastest", "Most expensive", "Slowest"):
            self.assertContains(self.response, text)
        for element_id in ("best-fare", "best-duration", "worst-fare", "worst-duration"):
            self.assertContains(self.response, f'id="{element_id}"')

    def test_best_and_worst_rows_have_distinct_classes(self):
        self.assertContains(self.response, "window-best")
        self.assertContains(self.response, "window-worst")

    def test_labeled_as_historical_not_guaranteed(self):
        self.assertContains(self.response, "Based on historical taxi data")
        self.assertContains(self.response, "actual fares and travel times may vary")

    def test_windows_js_loaded_after_filters_js(self):
        html = self.response.content.decode()
        self.assertIn("zones/js/windows.js", html)
        self.assertLess(html.index("zones/js/filters.js"), html.index("zones/js/windows.js"))


class WindowsJsTests(SimpleTestCase):
    """windows.js reads /api/routes/windows for the selected zones and day."""

    def setUp(self):
        self.js = (STATIC_DIR / "js" / "windows.js").read_text()

    def test_calls_windows_api(self):
        self.assertIn("/api/routes/windows", self.js)

    def test_needs_a_dropoff(self):
        # Team decision 2026-10-23: best and worst are for a trip, so the
        # section stays hidden until both zones are selected.
        load = self.js.split("function loadWindows", 1)[1].split("fetch(", 1)[0]
        early_return = load.split("return;", 1)[0]
        self.assertIn("dropoff === null", early_return)
        self.assertIn("bestRow.hidden = true", early_return)
        self.assertIn("worstRow.hidden = true", early_return)
        # With a dropoff always present, `to` is always sent.
        self.assertIn("to: dropoff", load)

    def test_writes_best_and_worst_lines(self):
        for name in ("best", "worst"):
            self.assertIn(f"data.{name}.fare", self.js)
            self.assertIn(f"data.{name}.duration", self.js)

    def test_shows_not_enough_data(self):
        self.assertIn("'Not enough data'", self.js)

    def test_listens_to_selection_time_and_map_events(self):
        self.assertIn("taxiscope:zones-selected", self.js)
        self.assertIn("taxiscope:time-changed", self.js)
        self.assertIn("taxiscope:map-ready", self.js)

    def test_ignores_older_responses(self):
        self.assertIn("windowsSequence", self.js)

    def test_shows_an_error_if_loading_fails(self):
        catch_body = self.js.split(".catch(", 1)[1]
        self.assertIn("Could not load", catch_body)

    def test_writes_text_not_html(self):
        self.assertNotIn("innerHTML", self.js)


class WindowsCssTests(SimpleTestCase):
    """Best and worst rows look different."""

    def test_best_and_worst_have_their_own_colors(self):
        css = (STATIC_DIR / "css" / "map.css").read_text()
        self.assertIn(".window-best", css)
        self.assertIn(".window-worst", css)
