"""US19 #48: suggest a cheaper adjacent pickup zone."""

from datetime import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from routes.planning import cheaper_nearby
from zones.models import RouteHourStats, Zone
from zones.stats import load_zone_neighbors
from zones.views import NYC_TZ

# Real ids from zones/data/zone_neighbors.json.
# Midtown Center (161) borders 162, 163, 164, 170 and 230.
MIDTOWN_CENTER, MIDTOWN_EAST, MIDTOWN_NORTH, MIDTOWN_SOUTH = 161, 162, 163, 164
MURRAY_HILL, TIMES_SQ = 170, 230
TURTLE_BAY_SOUTH = 233  # borders Midtown East, not Midtown Center
JFK = 132  # not adjacent to Midtown
ROOSEVELT_ISLAND = 202  # island: no neighbours
UNKNOWN = 264  # in the zone table, no shape and no neighbours

FRIDAY, SATURDAY = 4, 5


@override_settings(MIN_TRIP_COUNT=5)
class NearbyTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        names = {
            MIDTOWN_CENTER: "Midtown Center",
            MIDTOWN_EAST: "Midtown East",
            MIDTOWN_NORTH: "Midtown North",
            MIDTOWN_SOUTH: "Midtown South",
            MURRAY_HILL: "Murray Hill",
            TIMES_SQ: "Times Sq/Theatre District",
            TURTLE_BAY_SOUTH: "UN/Turtle Bay South",
            ROOSEVELT_ISLAND: "Roosevelt Island",
        }
        for zone_id, name in names.items():
            Zone.objects.create(zone_id=zone_id, name=name, borough="Manhattan")
        Zone.objects.create(zone_id=JFK, name="JFK Airport", borough="Queens")
        Zone.objects.create(zone_id=UNKNOWN, name="Unknown", borough="Unknown")

    def row(
        self, pickup, fare, dropoff=JFK, day=FRIDAY, hour=17, count=10, duration=45.0
    ):
        return RouteHourStats.objects.create(
            pickup_zone_id=pickup,
            dropoff_zone_id=dropoff,
            day_of_week=day,
            hour=hour,
            trip_count=count,
            avg_duration_min=duration,
            fare_min=Decimal("20.00"),
            fare_avg=Decimal(fare),
            fare_max=Decimal("90.00"),
        )

    def nearby(self, pickup=MIDTOWN_CENTER, dropoff=JFK, day=FRIDAY, hour=17):
        return cheaper_nearby(pickup, dropoff, day, hour)

    def suggested(self, result):
        return [s["zone_id"] for s in result["suggestions"]]


class CheaperNearbyTests(NearbyTestCase):
    def test_suggests_cheaper_adjacent_zone(self):
        self.row(MIDTOWN_CENTER, "62.10")
        self.row(MIDTOWN_SOUTH, "57.40")
        result = self.nearby()
        self.assertTrue(result["enough_data"])
        self.assertEqual(self.suggested(result), [MIDTOWN_SOUTH])

    def test_suggestion_fields(self):
        self.row(MIDTOWN_CENTER, "62.10", duration=48.2, count=40)
        self.row(MIDTOWN_SOUTH, "57.40", duration=45.0, count=22)
        result = self.nearby()
        self.assertEqual(
            result["current"],
            {
                "trip_count": 40,
                "fare_avg": Decimal("62.10"),
                "avg_duration_min": 48.2,
            },
        )
        self.assertEqual(
            result["suggestions"],
            [
                {
                    "zone_id": MIDTOWN_SOUTH,
                    "name": "Midtown South",
                    "borough": "Manhattan",
                    "trip_count": 22,
                    "fare_avg": Decimal("57.40"),
                    "avg_duration_min": 45.0,
                    "saving": Decimal("4.70"),
                }
            ],
        )

    def test_saving_is_current_minus_neighbour_fare(self):
        self.row(MIDTOWN_CENTER, "30.01")
        self.row(TIMES_SQ, "29.99")
        self.assertEqual(self.nearby()["suggestions"][0]["saving"], Decimal("0.02"))

    def test_ignores_cheaper_zone_that_is_not_adjacent(self):
        self.row(MIDTOWN_CENTER, "62.10")
        self.row(TURTLE_BAY_SOUTH, "20.00")
        self.assertEqual(self.suggested(self.nearby()), [])

    def test_uses_only_the_same_day_and_hour(self):
        self.row(MIDTOWN_CENTER, "62.10")
        self.row(MIDTOWN_SOUTH, "40.00", hour=16)
        self.row(MIDTOWN_EAST, "40.00", day=SATURDAY)
        self.row(MIDTOWN_NORTH, "40.00", dropoff=MURRAY_HILL)
        self.assertEqual(self.suggested(self.nearby()), [])

    def test_equal_or_higher_fare_not_suggested(self):
        self.row(MIDTOWN_CENTER, "50.00")
        self.row(MIDTOWN_EAST, "50.00")
        self.row(MIDTOWN_NORTH, "55.00")
        result = self.nearby()
        self.assertTrue(result["enough_data"])
        self.assertEqual(result["suggestions"], [])

    def test_neighbour_below_min_trip_count_skipped(self):
        self.row(MIDTOWN_CENTER, "62.10")
        self.row(MIDTOWN_EAST, "40.00", count=4)
        self.row(MIDTOWN_SOUTH, "60.00", count=5)
        self.assertEqual(self.suggested(self.nearby()), [MIDTOWN_SOUTH])

    def test_never_suggests_destination(self):
        # Midtown East is next to Midtown Center and is the destination.
        self.row(MIDTOWN_CENTER, "15.00", dropoff=MIDTOWN_EAST)
        self.row(MIDTOWN_EAST, "8.00", dropoff=MIDTOWN_EAST)
        self.row(MIDTOWN_NORTH, "12.00", dropoff=MIDTOWN_EAST)
        result = self.nearby(dropoff=MIDTOWN_EAST)
        self.assertEqual(self.suggested(result), [MIDTOWN_NORTH])
        self.assertEqual(result["neighbor_count"], 4)

    def test_at_most_three_biggest_saving_first(self):
        self.row(MIDTOWN_CENTER, "62.10")
        self.row(MIDTOWN_EAST, "61.00")
        self.row(MIDTOWN_NORTH, "50.00")
        self.row(MIDTOWN_SOUTH, "55.00")
        self.row(MURRAY_HILL, "58.00")
        self.row(TIMES_SQ, "60.00")
        result = self.nearby()
        self.assertEqual(
            self.suggested(result), [MIDTOWN_NORTH, MIDTOWN_SOUTH, MURRAY_HILL]
        )
        self.assertEqual(result["neighbor_count"], 5)

    def test_tie_goes_to_lower_zone_id(self):
        self.row(MIDTOWN_CENTER, "62.10")
        self.row(TIMES_SQ, "55.00")
        self.row(MIDTOWN_SOUTH, "55.00")
        self.assertEqual(self.suggested(self.nearby()), [MIDTOWN_SOUTH, TIMES_SQ])

    def test_two_queries_for_all_neighbours(self):
        self.row(MIDTOWN_CENTER, "62.10")
        for zone_id in (MIDTOWN_EAST, MIDTOWN_NORTH, MIDTOWN_SOUTH, TIMES_SQ):
            self.row(zone_id, "50.00")
        with self.assertNumQueries(2):
            self.nearby()

    def test_current_route_too_few_trips(self):
        self.row(MIDTOWN_CENTER, "62.10", count=4)
        self.row(MIDTOWN_SOUTH, "40.00")
        result = self.nearby()
        self.assertFalse(result["enough_data"])
        self.assertEqual(
            result["current"],
            {"trip_count": 4, "fare_avg": None, "avg_duration_min": None},
        )
        self.assertEqual(result["suggestions"], [])

    def test_no_row_for_current_route(self):
        self.row(MIDTOWN_SOUTH, "40.00")
        result = self.nearby()
        self.assertFalse(result["enough_data"])
        self.assertEqual(result["current"]["trip_count"], 0)
        self.assertEqual(result["suggestions"], [])

    def test_island_pickup_has_no_neighbors(self):
        self.row(ROOSEVELT_ISLAND, "40.00")
        result = self.nearby(pickup=ROOSEVELT_ISLAND)
        self.assertTrue(result["enough_data"])
        self.assertEqual(result["neighbor_count"], 0)
        self.assertEqual(result["suggestions"], [])

    def test_unknown_zone_in_file_has_no_neighbors(self):
        result = self.nearby(pickup=UNKNOWN)
        self.assertEqual(result["neighbor_count"], 0)
        self.assertEqual(result["suggestions"], [])

    def test_neighbors_file_loaded_once(self):
        self.assertIs(load_zone_neighbors(), load_zone_neighbors())
        self.assertEqual(
            load_zone_neighbors()[MIDTOWN_CENTER],
            [MIDTOWN_EAST, MIDTOWN_NORTH, MIDTOWN_SOUTH, MURRAY_HILL, TIMES_SQ],
        )


class NearbyApiTests(NearbyTestCase):
    url = reverse("routes:nearby_api")

    def get(self, **params):
        return self.client.get(self.url, params)

    def test_returns_suggestions_as_json(self):
        self.row(MIDTOWN_CENTER, "62.10", duration=48.2, count=40)
        self.row(MIDTOWN_SOUTH, "57.40", count=22)
        response = self.get(**{"from": MIDTOWN_CENTER, "to": JFK, "day": 4, "hour": 17})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "from": MIDTOWN_CENTER,
                "to": JFK,
                "day": 4,
                "hour": 17,
                "enough_data": True,
                "current": {
                    "trip_count": 40,
                    "fare_avg": "62.10",
                    "avg_duration_min": 48.2,
                },
                "neighbor_count": 5,
                "suggestions": [
                    {
                        "zone_id": MIDTOWN_SOUTH,
                        "name": "Midtown South",
                        "borough": "Manhattan",
                        "trip_count": 22,
                        "fare_avg": "57.40",
                        "avg_duration_min": 45.0,
                        "saving": "4.70",
                    }
                ],
            },
        )

    def test_not_enough_data_is_200_with_nulls(self):
        response = self.get(**{"from": MIDTOWN_CENTER, "to": JFK, "day": 4, "hour": 3})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["enough_data"])
        self.assertIsNone(data["current"]["fare_avg"])
        self.assertEqual(data["suggestions"], [])

    def test_same_zone_trip_never_suggests_the_pickup(self):
        self.row(MIDTOWN_CENTER, "10.00", dropoff=MIDTOWN_CENTER)
        self.row(MIDTOWN_EAST, "8.00", dropoff=MIDTOWN_CENTER)
        response = self.get(
            **{"from": MIDTOWN_CENTER, "to": MIDTOWN_CENTER, "day": 4, "hour": 17}
        )
        self.assertEqual(response.status_code, 200)
        ids = [s["zone_id"] for s in response.json()["suggestions"]]
        self.assertNotIn(MIDTOWN_CENTER, ids)
        self.assertEqual(ids, [MIDTOWN_EAST])

    def test_defaults_to_current_nyc_day_and_hour(self):
        friday_5pm = datetime(2026, 10, 30, 17, 20, tzinfo=NYC_TZ)
        with mock.patch("routes.views.datetime") as fake:
            fake.now.return_value = friday_5pm
            response = self.get(**{"from": MIDTOWN_CENTER, "to": JFK})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["day"], response.json()["hour"]), (4, 17))
        fake.now.assert_called_once_with(NYC_TZ)

    def test_bad_requests_return_400(self):
        good = {"from": MIDTOWN_CENTER, "to": JFK, "day": 4, "hour": 17}
        cases = [
            {"to": JFK, "day": 4, "hour": 17},  # no from
            {"from": MIDTOWN_CENTER, "day": 4, "hour": 17},  # no to
            {**good, "to": ""},
            {**good, "to": "abc"},
            {**good, "from": 999},  # unknown zone
            {**good, "to": 999},
            {**good, "from": 0},
            {**good, "day": 7},
            {**good, "day": -1},
            {**good, "hour": 24},
            {**good, "hour": "x"},
        ]
        for params in cases:
            with self.subTest(params=params):
                response = self.get(**params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_post_not_allowed(self):
        response = self.client.post(self.url, {"from": MIDTOWN_CENTER, "to": JFK})
        self.assertEqual(response.status_code, 405)

    def test_public_without_sign_in(self):
        response = self.get(**{"from": MIDTOWN_CENTER, "to": JFK, "day": 4, "hour": 17})
        self.assertEqual(response.status_code, 200)

    def test_map_has_nearby_section_with_label(self):
        response = self.client.get(reverse("zones:map"))
        self.assertContains(response, 'id="nearby-panel"')
        self.assertContains(
            response, "Based on past trips (March to May 2026), not guaranteed."
        )
        self.assertContains(response, "routes/js/nearby.js")
