"""US18 #47: adjacent zones file, built by scripts/build_zone_neighbors.py."""

import csv
import importlib.util
import json
import unittest
from pathlib import Path

from django.test import SimpleTestCase

DATA = Path(__file__).resolve().parent.parent / "data"
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_zone_neighbors.py"

MIDTOWN_CENTER, MIDTOWN_EAST, MIDTOWN_NORTH, MIDTOWN_SOUTH, TIMES_SQ = (
    161,
    162,
    163,
    164,
    230,
)
JFK, JAMAICA_BAY, HOWARD_BEACH, SOUTH_OZONE_PARK = 132, 2, 124, 216
ST_GEORGE, STAPLETON, WEST_BRIGHTON = 206, 221, 245
BATTERY_PARK, BROOKLYN_HEIGHTS, LIC_HUNTERS_POINT = 12, 33, 145
ROOSEVELT_ISLAND, NEWARK_AIRPORT, MARBLE_HILL = 202, 1, 153


class ZoneNeighborsFileTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with (DATA / "zone_neighbors.json").open(encoding="utf-8") as f:
            cls.raw = json.load(f)
        cls.neighbors = {int(k): set(v) for k, v in cls.raw.items()}
        with (DATA / "taxi_zones.geojson").open(encoding="utf-8") as f:
            cls.shape_ids = {
                feature["properties"]["LocationID"]
                for feature in json.load(f)["features"]
            }
        with (DATA / "taxi_zone_lookup.csv").open(encoding="utf-8") as f:
            cls.borough = {
                int(r["LocationID"]): r["Borough"] for r in csv.DictReader(f)
            }

    def test_covers_every_zone_with_a_shape(self):
        self.assertEqual(set(self.neighbors), self.shape_ids)

    def test_lists_are_sorted_ids_without_duplicates(self):
        for zone, ids in self.raw.items():
            with self.subTest(zone=zone):
                self.assertEqual(ids, sorted(set(ids)))
                self.assertTrue(set(ids) <= self.shape_ids)

    def test_adjacency_is_two_way_and_no_zone_lists_itself(self):
        for zone, ids in self.neighbors.items():
            self.assertNotIn(zone, ids)
            for other in ids:
                self.assertIn(zone, self.neighbors[other], f"{zone} -> {other}")

    def test_spot_check_midtown(self):
        self.assertTrue(
            {MIDTOWN_EAST, MIDTOWN_NORTH, MIDTOWN_SOUTH, TIMES_SQ}
            <= self.neighbors[MIDTOWN_CENTER]
        )

    def test_spot_check_jfk(self):
        self.assertTrue(
            {JAMAICA_BAY, HOWARD_BEACH, SOUTH_OZONE_PARK} <= self.neighbors[JFK]
        )

    def test_spot_check_staten_island(self):
        self.assertTrue({STAPLETON, WEST_BRIGHTON} <= self.neighbors[ST_GEORGE])
        self.assertEqual(
            {self.borough[z] for z in self.neighbors[ST_GEORGE]}, {"Staten Island"}
        )

    def test_zones_across_a_river_are_not_adjacent(self):
        self.assertNotIn(BROOKLYN_HEIGHTS, self.neighbors[BATTERY_PARK])
        self.assertEqual(
            {self.borough[z] for z in self.neighbors[LIC_HUNTERS_POINT]}, {"Queens"}
        )
        self.assertEqual(self.neighbors[ROOSEVELT_ISLAND], set())
        self.assertEqual(self.neighbors[NEWARK_AIRPORT], set())

    def test_manhattan_only_borders_the_bronx_at_marble_hill(self):
        for zone, ids in self.neighbors.items():
            if self.borough[zone] != "Manhattan":
                continue
            for other in ids:
                if self.borough[other] != "Manhattan":
                    self.assertEqual(
                        (zone, self.borough[other]), (MARBLE_HILL, "Bronx")
                    )


def _load_script():
    spec = importlib.util.spec_from_file_location("build_zone_neighbors", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    import shapely  # noqa: F401  (only installed to rebuild the file)

    HAVE_SHAPELY = True
except ImportError:
    HAVE_SHAPELY = False


@unittest.skipUnless(HAVE_SHAPELY, "shapely is only needed to rebuild the file")
class AdjacencyRuleTests(SimpleTestCase):
    """The rule on tiny squares (in metres): shared edge yes, corner or gap no."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = _load_script()
        from shapely.geometry import box

        cls.box = staticmethod(box)

    def neighbors(self, **zones):
        return self.script.find_neighbors(
            {int(k[1:]): self.box(*v) for k, v in zones.items()}
        )

    def test_shared_edge_is_adjacent(self):
        result = self.neighbors(z1=(0, 0, 100, 100), z2=(100, 0, 200, 100))
        self.assertEqual(result, {"1": [2], "2": [1]})

    def test_touching_corner_is_not_adjacent(self):
        result = self.neighbors(z1=(0, 0, 100, 100), z2=(100, 100, 200, 200))
        self.assertEqual(result, {"1": [], "2": []})

    def test_gap_like_a_river_is_not_adjacent(self):
        result = self.neighbors(z1=(0, 0, 100, 100), z2=(130, 0, 230, 100))
        self.assertEqual(result, {"1": [], "2": []})

    def test_tiny_rounding_gap_still_counts(self):
        result = self.neighbors(z1=(0, 0, 100, 100), z2=(100.5, 0, 200, 100))
        self.assertEqual(result, {"1": [2], "2": [1]})
