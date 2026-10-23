"""US3 #5: View Demand Heatmap — static file tests for heatmap.js."""

from pathlib import Path

from django.test import SimpleTestCase


STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "zones"


class HeatmapJsErrorTests(SimpleTestCase):
    """When the heatmap request fails, the error message is visible."""

    def setUp(self):
        self.js = (STATIC_DIR / "js" / "heatmap.js").read_text()
        load = self.js.split("function loadHeatmap", 1)[1]
        self.catch_body = load.split(".catch(", 1)[1].split("function ", 1)[0]

    def test_catch_writes_error_message(self):
        self.assertIn("Failed to load heatmap data", self.catch_body)

    def test_catch_shows_the_panel(self):
        # Without this, the message is written into a hidden panel and the
        # user sees nothing (review note on PR #29).
        self.assertIn("showHeatmap()", self.catch_body)
