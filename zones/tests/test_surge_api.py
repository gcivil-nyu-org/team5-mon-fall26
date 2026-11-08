"""US29 #76: GET /api/zones/:id/surge, the likely surge hours of a pickup
zone (Uber and Lyft fare per mile against the zone's median hour)."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from zones.models import RideshareZoneHourStats, Zone
from zones.stats import surge_grid


def add_cell(zone, day, hour, fare_per_mile, trip_count=50, wait_count=None, wait=4.0):
    return RideshareZoneHourStats.objects.create(
        zone=zone,
        day_of_week=day,
        hour=hour,
        trip_count=trip_count,
        avg_duration_min=15.0,
        fare_min=Decimal("8.00"),
        fare_avg=Decimal("25.00"),
        fare_max=Decimal("60.00"),
        avg_wait_min=wait,
        wait_count=trip_count if wait_count is None else wait_count,
        fare_per_mile=None if fare_per_mile is None else Decimal(fare_per_mile),
    )


class SurgeData:
    """Midtown Center's counted hours have fare per mile 6.00, 7.00, 7.50,
    8.00, 9.00, 10.00 and 12.00: median 8.00, so the surge line is
    8.00 x 1.25 = 10.00. Monday 18:00 (9.00) is under it, Friday 18:00
    (10.00) is exactly on it. A 4-trip cell (40.00) is not counted."""

    @classmethod
    def setUpTestData(cls):
        cls.midtown = Zone.objects.create(
            zone_id=161, name="Midtown Center", borough="Manhattan"
        )
        cls.empty = Zone.objects.create(
            zone_id=12, name="Battery Park", borough="Manhattan"
        )
        for hour, fpm in [(8, "6.00"), (9, "7.00"), (10, "8.00"), (11, "7.50")]:
            add_cell(cls.midtown, 0, hour, fpm)
        add_cell(cls.midtown, 0, 18, "9.00")
        add_cell(cls.midtown, 4, 18, "10.00", wait=7.25)
        # Very high fare per mile but only 4 trips: never marked, not counted.
        add_cell(cls.midtown, 5, 2, "40.00", trip_count=4)
        # Enough trips but only 3 valid waits: marked, wait hidden.
        add_cell(cls.midtown, 5, 23, "12.00", wait_count=3)


class SurgeGridTests(SurgeData, TestCase):
    def setUp(self):
        self.result = surge_grid(161)
        self.grid = self.result["surge"]

    def test_grid_is_7_by_24(self):
        self.assertEqual(len(self.grid), 7)
        self.assertTrue(all(len(day) == 24 for day in self.grid))

    def test_median_of_counted_hours_only(self):
        # 6, 7, 7.5, 8, 9, 10, 12 (the 4-trip 40.00 is left out) -> 8.00.
        self.assertTrue(self.result["enough_data"])
        self.assertEqual(self.result["median_fare_per_mile"], Decimal("8.00"))
        self.assertEqual(self.result["surge_ratio_threshold"], 1.25)
        self.assertEqual(self.result["min_trip_count"], 5)

    def test_marks_hours_at_or_over_the_ratio(self):
        # Line: 8.00 x 1.25 = 10.00. Friday 18:00 is exactly on it.
        friday = self.grid[4][18]
        self.assertTrue(friday["likely_surge"])
        self.assertEqual(friday["fare_per_mile"], Decimal("10.00"))
        self.assertEqual(friday["surge_ratio"], 1.25)
        self.assertEqual(friday["avg_wait_min"], 7.25)
        self.assertTrue(self.grid[5][23]["likely_surge"])

    def test_hours_under_the_ratio_are_not_marked(self):
        monday_18 = self.grid[0][18]
        self.assertFalse(monday_18["likely_surge"])
        self.assertEqual(monday_18["surge_ratio"], 1.13)  # 9 / 8 = 1.125, half up
        self.assertEqual(monday_18["fare_per_mile"], Decimal("9.00"))

    def test_too_few_trips_is_never_marked_and_shows_no_stats(self):
        cell = self.grid[5][2]
        self.assertEqual(
            cell,
            {
                "trip_count": 4,
                "fare_per_mile": None,
                "avg_wait_min": None,
                "surge_ratio": None,
                "likely_surge": False,
            },
        )

    def test_too_few_waits_hides_only_the_wait(self):
        cell = self.grid[5][23]
        self.assertIsNone(cell["avg_wait_min"])
        self.assertEqual(cell["fare_per_mile"], Decimal("12.00"))

    def test_missing_cell(self):
        self.assertEqual(self.grid[6][0]["trip_count"], None)
        self.assertFalse(self.grid[6][0]["likely_surge"])

    def test_zone_without_rideshare_data(self):
        result = surge_grid(12)
        self.assertFalse(result["enough_data"])
        self.assertIsNone(result["median_fare_per_mile"])
        self.assertFalse(
            any(cell["likely_surge"] for day in result["surge"] for cell in day)
        )

    def test_null_fare_per_mile_is_not_counted(self):
        add_cell(self.empty, 0, 8, None)
        add_cell(self.empty, 0, 9, "5.00")
        result = surge_grid(12)
        self.assertEqual(result["median_fare_per_mile"], Decimal("5.00"))
        self.assertIsNone(result["surge"][0][8]["fare_per_mile"])
        self.assertFalse(result["surge"][0][8]["likely_surge"])

    def test_even_median_is_exact_for_the_rule(self):
        # 4.00, 4.00, 5.00, 5.01, 6.25, 6.26: median 5.005 (shown 5.01).
        # Exact line 6.25625: 6.26 is marked, 6.25 is not. With the shown
        # 5.01 the line would be 6.2625 and 6.26 would not be marked.
        for hour, fpm in [(1, "4.00"), (2, "4.00"), (3, "5.00"), (4, "5.01")]:
            add_cell(self.empty, 0, hour, fpm)
        add_cell(self.empty, 1, 1, "6.26")
        add_cell(self.empty, 1, 2, "6.25")
        result = surge_grid(12)
        self.assertEqual(result["median_fare_per_mile"], Decimal("5.01"))
        self.assertTrue(result["surge"][1][1]["likely_surge"])
        self.assertFalse(result["surge"][1][2]["likely_surge"])

    @override_settings(SURGE_FARE_PER_MILE_RATIO=Decimal("1.10"))
    def test_ratio_comes_from_settings(self):
        result = surge_grid(161)
        # Line 8.80: Monday 18:00 (9.00) is now marked.
        self.assertTrue(result["surge"][0][18]["likely_surge"])
        self.assertEqual(result["surge_ratio_threshold"], 1.1)

    @override_settings(MIN_TRIP_COUNT=60)
    def test_minimum_comes_from_settings(self):
        result = surge_grid(161)
        self.assertFalse(result["enough_data"])


class SurgeApiTests(SurgeData, TestCase):
    def url(self, zone_id):
        return reverse("zones:surge_api", args=[zone_id])

    def test_url(self):
        self.assertEqual(self.url(161), "/api/zones/161/surge")

    def test_response(self):
        response = self.client.get(self.url(161))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            set(data),
            {
                "zone_id",
                "zone_name",
                "borough",
                "enough_data",
                "median_fare_per_mile",
                "surge_ratio_threshold",
                "min_trip_count",
                "surge",
            },
        )
        self.assertEqual(data["zone_name"], "Midtown Center")
        self.assertEqual(data["median_fare_per_mile"], "8.00")
        self.assertEqual(
            data["surge"][4][18],
            {
                "trip_count": 50,
                "fare_per_mile": "10.00",
                "avg_wait_min": 7.25,
                "surge_ratio": 1.25,
                "likely_surge": True,
            },
        )

    def test_unknown_zone_is_404(self):
        response = self.client.get(self.url(999))
        self.assertEqual(response.status_code, 404)

    def test_only_get(self):
        self.assertEqual(self.client.post(self.url(161)).status_code, 405)


class SurgeTemplateTests(TestCase):
    """The heatmap has the toggle and a legend that explains the estimate."""

    def setUp(self):
        self.response = self.client.get(reverse("zones:map"))
        self.html = self.response.content.decode()

    def test_toggle_is_in_the_heatmap_controls(self):
        self.assertContains(self.response, 'id="surge-toggle"')
        self.assertContains(self.response, "Show likely surge hours")
        self.assertLess(
            self.html.index('id="heatmap-panel"'), self.html.index('id="surge-toggle"')
        )

    def test_legend_explains_the_estimate(self):
        self.assertContains(self.response, 'id="surge-legend"')
        self.assertContains(self.response, "real surge multipliers are not public")
        self.assertContains(self.response, "1.25")
