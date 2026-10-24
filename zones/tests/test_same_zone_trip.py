"""US5 #7 follow-up: a trip within one zone — template and static file tests.
A "Trip within this zone" button sets the dropoff to the pickup zone; the
US2 click rules in selectZone are unchanged."""

import re
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse


STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "zones"


def function_body(js, name):
    """The text of a top-level `function name(...)` up to its closing brace."""
    return js.split(f"function {name}(", 1)[1].split("\n}\n", 1)[0]


class SameZoneTemplateTests(TestCase):
    """The selection panel has the hidden "Trip within this zone" button."""

    def setUp(self):
        self.content = self.client.get(reverse("zones:map")).content.decode()
        self.button = re.search(r'<button[^>]*id="same-zone-trip"[^>]*>', self.content)

    def test_same_zone_button_present(self):
        self.assertRegex(
            self.content,
            r'<button[^>]*id="same-zone-trip"[^>]*>Trip within this zone</button>',
        )

    def test_same_zone_button_hidden_by_default(self):
        self.assertIsNotNone(self.button)
        self.assertIn("hidden", self.button.group(0))

    def test_same_zone_button_is_type_button(self):
        self.assertIsNotNone(self.button)
        self.assertIn('type="button"', self.button.group(0))

    def test_same_zone_button_inside_selection_panel(self):
        position = self.content.index('id="same-zone-trip"')
        self.assertLess(self.content.index('class="zone-selection"'), position)
        self.assertLess(position, self.content.index('id="fare-range"'))


class SameZoneJsTests(SimpleTestCase):
    """filters.js sets the dropoff to the pickup and marks the zone as both."""

    def setUp(self):
        self.js = (STATIC_DIR / "js" / "filters.js").read_text()

    def test_select_same_zone_function(self):
        self.assertIn("function selectSameZone", self.js)

    def test_select_same_zone_sets_dropoff_to_pickup(self):
        self.assertIn("dropoffZoneId = pickupZoneId", function_body(self.js, "selectSameZone"))

    def test_select_same_zone_dispatches_zones_selected(self):
        self.assertIn("taxiscope:zones-selected", function_body(self.js, "selectSameZone"))

    def test_button_wired_on_map_ready(self):
        self.assertIn('sameZoneBtn.addEventListener("click", selectSameZone)', self.js)

    def test_button_visibility_rule(self):
        panel = function_body(self.js, "updateSelectionPanel")
        self.assertIn("sameZoneBtn.hidden", panel)
        self.assertIn("pickupZoneId", panel.split("sameZoneBtn.hidden", 1)[1])
        self.assertIn("dropoffZoneId", panel.split("sameZoneBtn.hidden", 1)[1])

    def test_panel_shows_same_zone_text(self):
        self.assertIn('"same zone"', function_body(self.js, "updateSelectionPanel"))

    def test_style_zone_handles_both(self):
        style = function_body(self.js, "styleZone")
        self.assertIn("isPickup && isDropoff", style)
        self.assertLess(style.index("isPickup && isDropoff"), style.index("if (isPickup)"))

    def test_outline_is_dashed_dropoff_color(self):
        outline = function_body(self.js, "updateSameZoneOutline")
        self.assertIn("dashArray", outline)
        self.assertIn("DROPOFF_COLOR", outline)

    def test_outline_in_own_non_interactive_pane(self):
        self.assertIn("createPane", self.js)
        self.assertIn("interactive: false", function_body(self.js, "updateSameZoneOutline"))

    def test_outline_updated_on_every_selection_change(self):
        for name in ("selectZone", "clearPickup", "clearDropoff", "selectSameZone"):
            with self.subTest(function=name):
                self.assertIn("updateSameZoneOutline()", function_body(self.js, name))

    def test_select_zone_rules_unchanged(self):
        # US2 #4: clicking the pickup clears everything, clicking the dropoff
        # clears it, the first click sets the pickup, any other click sets
        # or replaces the dropoff.
        self.assertIn(
            "  if (zoneId === pickupZoneId) {\n"
            "    pickupZoneId = null;\n"
            "    dropoffZoneId = null;\n"
            "  } else if (zoneId === dropoffZoneId) {\n"
            "    dropoffZoneId = null;\n"
            "  } else if (pickupZoneId === null) {\n"
            "    pickupZoneId = zoneId;\n"
            "  } else {\n"
            "    dropoffZoneId = zoneId;\n"
            "  }\n",
            function_body(self.js, "selectZone"),
        )
        clear_dropoff = function_body(self.js, "clearDropoff")
        self.assertIn("dropoffZoneId = null;", clear_dropoff)
        self.assertNotIn("pickupZoneId = null", clear_dropoff)


class SameZoneSummaryJsTests(SimpleTestCase):
    """The shared summary labels a trip within one zone as such."""

    def setUp(self):
        self.js = (STATIC_DIR / "js" / "trip-summary.js").read_text()

    def test_summary_route_for_trip_within_one_zone(self):
        route_label = function_body(self.js, "updateRouteLabel")
        self.assertIn("pickupZoneId === dropoffZoneId", route_label)
        self.assertIn("Trips within this zone", route_label)


class SameZoneCssTests(SimpleTestCase):
    """The CSS styles the button without overriding its hidden attribute."""

    def setUp(self):
        self.css = (STATIC_DIR / "css" / "map.css").read_text()

    def test_same_zone_btn_class(self):
        self.assertIn(".same-zone-btn", self.css)

    def test_same_zone_btn_does_not_override_hidden(self):
        rules = re.findall(r"\.same-zone-btn[^{]*\{([^}]*)\}", self.css)
        self.assertTrue(rules)
        for rule in rules:
            self.assertNotIn("display", rule)
