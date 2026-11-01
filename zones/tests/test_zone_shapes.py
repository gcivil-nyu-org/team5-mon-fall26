import json
from pathlib import Path

from django.test import SimpleTestCase

SHAPES_PATH = Path(__file__).resolve().parent.parent / "data" / "taxi_zones.geojson"

# Rough NYC bounding box in WGS84. A point outside it means the conversion
# from the shapefile's coordinate system failed or lon/lat got swapped.
MIN_LON, MAX_LON = -74.3, -73.6
MIN_LAT, MAX_LAT = 40.45, 40.95


def iter_positions(geometry):
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    for polygon in polygons:
        for ring in polygon:
            yield from ring


class ZoneShapesFileTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with SHAPES_PATH.open(encoding="utf-8") as f:
            cls.data = json.load(f)
        cls.features = cls.data["features"]

    def test_is_a_feature_collection(self):
        self.assertEqual(self.data["type"], "FeatureCollection")
        self.assertIsInstance(self.features, list)
        for feature in self.features:
            self.assertEqual(feature["type"], "Feature")

    def test_has_263_unique_location_ids_from_1_to_263(self):
        # Zones 264 and 265 (Unknown / Outside of NYC) have no shape.
        ids = [f["properties"]["LocationID"] for f in self.features]

        self.assertEqual(len(self.features), 263)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(range(1, 264)))

    def test_every_feature_has_properties_and_polygon_geometry(self):
        for feature in self.features:
            props = feature["properties"]
            with self.subTest(location_id=props.get("LocationID")):
                self.assertIsInstance(props["LocationID"], int)
                self.assertTrue(props["zone"])
                self.assertTrue(props["borough"])
                self.assertIn(feature["geometry"]["type"], ("Polygon", "MultiPolygon"))

    def test_every_coordinate_is_lon_lat_inside_nyc(self):
        for feature in self.features:
            location_id = feature["properties"]["LocationID"]
            for lon, lat in iter_positions(feature["geometry"]):
                if not (MIN_LON <= lon <= MAX_LON and MIN_LAT <= lat <= MAX_LAT):
                    self.fail(
                        f"LocationID {location_id}: [{lon}, {lat}] is outside NYC"
                    )
