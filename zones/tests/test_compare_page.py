"""US22 #69: Compare two zones side by side, on its own public page."""

from datetime import datetime
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from zones.models import Zone
from zones.views import NYC_TZ

# Scripts and panels of the map page that the compare page must not load.
MAP_ONLY_SCRIPTS = [
    "filters.js",
    "trip-summary.js",
    "fare.js",
    "windows.js",
    "save-route.js",
    "leave-by.js",
    "cheapest.js",
    "save-plan.js",
    "nearby.js",
    "day-plan.js",
]
MAP_ONLY_PANELS = [
    'id="pickup-zone"',
    'id="summary-panel"',
    'id="heatmap-panel"',
    'id="day-plan-panel"',
    'id="leave-by-panel"',
    'id="save-route-panel"',
]


class ComparePageTests(TestCase):
    def get(self):
        return self.client.get(reverse("zones:compare"))

    def test_works_without_signing_in(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "zones/compare.html")

    def test_url(self):
        self.assertEqual(reverse("zones:compare"), "/compare/")

    def test_same_header_filters_and_map_as_the_map_page(self):
        response = self.get()
        self.assertContains(response, "<h1>TaxiScope NYC</h1>")
        self.assertContains(response, 'class="account-nav"')
        self.assertContains(response, reverse("accounts:signin"))
        for element in ['id="day-filter"', 'id="hour-filter"', 'id="hour-value"']:
            self.assertContains(response, element)
        self.assertContains(response, 'id="filter-status"')
        self.assertContains(response, '<div id="map">')
        for asset in [
            "zones/vendor/leaflet/leaflet.js",
            "zones/js/map.js",
            "zones/js/heatmap.js",
            "zones/js/compare.js",
            "zones/css/map.css",
            "zones/css/compare.css",
        ]:
            self.assertContains(response, asset)

    def test_scripts_load_in_order_map_heatmap_compare(self):
        html = self.get().content.decode()
        positions = [
            html.index(name)
            for name in ["leaflet.js", "zones/js/map.js", "heatmap.js", "compare.js"]
        ]
        self.assertEqual(positions, sorted(positions))

    def test_none_of_the_map_page_panels_or_their_scripts(self):
        response = self.get()
        for script in MAP_ONLY_SCRIPTS:
            self.assertNotContains(response, script)
        for panel in MAP_ONLY_PANELS:
            self.assertNotContains(response, panel)

    def test_signed_in_header_shows_the_account(self):
        user = get_user_model().objects.create_user(
            "alex@example.com", "alex@example.com", "x"
        )
        self.client.force_login(user)
        response = self.get()
        self.assertContains(response, "alex@example.com")
        self.assertContains(response, reverse("accounts:signout"))

    def test_compare_card_has_two_sides_and_guiding_text(self):
        response = self.get()
        self.assertContains(response, 'id="compare-card"')
        self.assertContains(response, 'id="compare-a-zone"')
        self.assertContains(response, 'id="compare-b-zone"')
        self.assertContains(response, 'id="clear-a"')
        self.assertContains(response, 'id="clear-b"')
        self.assertContains(response, "Click a zone on the map to set A")

    def test_table_rows(self):
        response = self.get()
        for row in ["Average fare", "Typical time", "Trips this hour"]:
            self.assertContains(response, row)
        for side in "ab":
            for cell in ["fare-avg", "fare-range", "time", "trips"]:
                self.assertContains(response, f'id="{side}-{cell}"')

    def test_based_on_past_trips_line(self):
        self.assertContains(self.get(), "Based on past taxi trips (March to May 2026).")

    def test_weekly_pattern_is_closed_by_default(self):
        response = self.get()
        self.assertContains(response, "Show weekly pattern")
        self.assertContains(
            response,
            '<section id="weekly-strip" class="weekly-strip" hidden',
        )
        self.assertContains(response, 'name="compare-metric" value="trip_count"')
        self.assertContains(response, 'name="compare-metric" value="avg_duration_min"')

    def test_exit_compare_and_back_to_map_open_the_plain_map(self):
        html = self.get().content.decode()
        map_url = reverse("zones:map")
        self.assertIn(f'<a id="exit-compare" href="{map_url}">Exit compare</a>', html)
        self.assertIn(f'<a id="back-to-map" href="{map_url}">Back to map</a>', html)

    def test_min_trip_count_comes_from_settings(self):
        self.assertContains(
            self.get(), f'data-min-trip-count="{settings.MIN_TRIP_COUNT}"'
        )

    def test_filters_default_to_the_current_nyc_day_and_hour(self):
        now = datetime(2026, 11, 3, 17, 30, tzinfo=NYC_TZ)  # a Tuesday
        with patch("zones.views.datetime") as clock:
            clock.now.return_value = now
            response = self.get()
        self.assertContains(response, '<option value="1" selected>Tuesday</option>')
        self.assertContains(response, 'value="17"')
        self.assertContains(response, "17:00–17:59")

    def test_only_get(self):
        self.assertEqual(self.client.post(reverse("zones:compare")).status_code, 405)


class MapPageCompareLinkTests(TestCase):
    """The map page gains a "Compare" header link and nothing from the
    compare page itself (the rest of the map page is unchanged)."""

    def get(self):
        return self.client.get(reverse("zones:map"))

    def test_map_page_links_to_compare(self):
        self.assertContains(
            self.get(),
            f'<a id="compare-link" href="{reverse("zones:compare")}">Compare</a>',
            html=True,
        )

    def test_map_page_has_no_compare_card_strip_or_assets(self):
        response = self.get()
        self.assertNotContains(response, 'id="compare-card"')
        self.assertNotContains(response, 'id="weekly-strip"')
        self.assertNotContains(response, "compare.js")
        self.assertNotContains(response, "compare.css")

    def test_map_page_loads_compare_link_js(self):
        self.assertContains(self.get(), "zones/js/compare-link.js")


# ---- Added beyond the acceptance criteria (US22 Step 2) ----

# As rendered in the page (the apostrophe is escaped).
LINK_NOT_ON_MAP = escape("A zone in the link isn't on the map, so it was left out.")
LINK_SAME_ZONE = "The link named the same zone for A and B, so B was left out."


class CompareAdditionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 161 and 132 have shapes; 264 (Unknown) is in the zone table but has none.
        Zone.objects.create(zone_id=161, name="Midtown Center", borough="Manhattan")
        Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")
        Zone.objects.create(zone_id=7, name="Astoria", borough="Queens")
        Zone.objects.create(zone_id=264, name="Unknown", borough="Unknown")

    def get(self, **params):
        return self.client.get(reverse("zones:compare"), params)

    def test_fare_meaning_line(self):
        self.assertContains(
            self.get(),
            "Fares cover all trips starting in each zone, so they reflect "
            "typical trip length too.",
        )

    def test_address_sets_both_zones_day_and_hour(self):
        response = self.get(a=161, b=132, day=1, hour=17)
        self.assertContains(response, 'data-start-a="161"')
        self.assertContains(response, 'data-start-b="132"')
        self.assertContains(response, '<option value="1" selected>Tuesday</option>')
        self.assertContains(response, "17:00–17:59")
        self.assertNotContains(response, LINK_NOT_ON_MAP)

    def test_no_zones_in_the_address(self):
        response = self.get()
        self.assertContains(response, 'data-start-a=""')
        self.assertContains(response, 'data-start-b=""')
        self.assertNotContains(response, LINK_NOT_ON_MAP)

    def test_empty_values_are_not_an_error(self):
        response = self.get(a="", b="")
        self.assertContains(response, 'data-start-a=""')
        self.assertNotContains(response, LINK_NOT_ON_MAP)

    def test_bad_or_unknown_ids_are_left_out_with_a_message(self):
        for bad in ["abc", "999", "264", "0", "-3", "1.5", "99999999999"]:
            with self.subTest(a=bad):
                response = self.get(a=bad, b=132)
                self.assertContains(response, 'data-start-a=""')
                self.assertContains(response, 'data-start-b="132"')
                self.assertContains(response, LINK_NOT_ON_MAP)

    def test_a_bad_b_is_left_out_and_a_kept(self):
        response = self.get(a=161, b="zzz")
        self.assertContains(response, 'data-start-a="161"')
        self.assertContains(response, 'data-start-b=""')
        self.assertContains(response, LINK_NOT_ON_MAP)

    def test_the_same_zone_twice_keeps_only_a(self):
        response = self.get(a=161, b=161)
        self.assertContains(response, 'data-start-a="161"')
        self.assertContains(response, 'data-start-b=""')
        self.assertContains(response, LINK_SAME_ZONE)

    def test_day_or_hour_out_of_range_falls_back_to_now(self):
        now = datetime(2026, 11, 6, 8, 5, tzinfo=NYC_TZ)  # a Friday
        for params in [{"day": 7, "hour": 25}, {"day": "x", "hour": "-1"}]:
            with self.subTest(**params), patch("zones.views.datetime") as clock:
                clock.now.return_value = now
                response = self.get(**params)
                self.assertContains(
                    response, '<option value="4" selected>Friday</option>'
                )
                self.assertContains(response, "8:00–8:59")

    def test_day_and_hour_are_independent(self):
        now = datetime(2026, 11, 6, 8, 5, tzinfo=NYC_TZ)  # a Friday
        with patch("zones.views.datetime") as clock:
            clock.now.return_value = now
            response = self.get(day=6, hour=99)
        self.assertContains(response, '<option value="6" selected>Sunday</option>')
        self.assertContains(response, "8:00–8:59")

    def test_choose_from_list_has_zones_with_a_shape_by_borough_then_name(self):
        html = self.get().content.decode()
        for side in "ab":
            self.assertIn(f'id="{side}-choose"', html)
        self.assertIn("or choose from list", html)
        self.assertNotIn("Unknown: Unknown", html)
        a_list = html.split('id="a-choose"', 1)[1].split("</select>", 1)[0]
        options = [
            '<option value="161">Manhattan: Midtown Center</option>',
            '<option value="7">Queens: Astoria</option>',
            '<option value="132">Queens: JFK Airport</option>',
        ]
        positions = [a_list.index(option) for option in options]
        self.assertEqual(positions, sorted(positions))

    def test_swap_button_and_busiest_hour_row(self):
        response = self.get()
        self.assertContains(response, 'id="swap-zones"')
        self.assertContains(response, "Swap A ↔ B")
        self.assertContains(response, '<th scope="row">Busiest hour</th>')
        self.assertContains(response, 'id="a-busiest"')
        self.assertContains(response, 'id="b-busiest"')

    def test_weekly_pattern_has_a_colour_key(self):
        response = self.get()
        self.assertContains(response, 'id="weekly-key"')
        self.assertContains(response, "same scale for both zones")
