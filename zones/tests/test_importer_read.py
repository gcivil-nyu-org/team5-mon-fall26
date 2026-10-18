import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from zones.importer.read import RAW_COLUMNS, TripFileError, read_trips, read_zone_lookup
from zones.tests.importer_helpers import make_trips, write_parquet


class ReadZoneLookupTests(SimpleTestCase):
    def setUp(self):
        self.lookup = read_zone_lookup()

    def test_has_every_zone_once(self):
        self.assertEqual(list(self.lookup.columns), ["zone_id", "name", "borough"])
        self.assertEqual(len(self.lookup), 265)
        self.assertEqual(sorted(self.lookup["zone_id"]), list(range(1, 266)))

    def test_zone_fields_are_read(self):
        row = self.lookup.set_index("zone_id").loc[1]

        self.assertEqual(row["name"], "Newark Airport")
        self.assertEqual(row["borough"], "EWR")

    def test_unknown_zones_keep_their_na_text(self):
        # pandas would read "N/A" as missing without keep_default_na=False.
        rows = self.lookup.set_index("zone_id")

        self.assertEqual(rows.loc[264, "name"], "N/A")
        self.assertEqual(rows.loc[264, "borough"], "Unknown")
        self.assertEqual(rows.loc[265, "name"], "Outside of NYC")
        self.assertEqual(rows.loc[265, "borough"], "N/A")
        self.assertFalse(self.lookup.isna().any().any())


class ReadTripsTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "trips.parquet"

    def test_returns_only_our_renamed_columns(self):
        write_parquet(
            make_trips({}, {"pickup_zone_id": 4}),
            self.path,
            extra_columns={"VendorID": 2, "Airport_fee": 0.0},
        )

        trips = read_trips(self.path)

        self.assertEqual(list(trips.columns), list(RAW_COLUMNS.values()))
        self.assertEqual(len(trips), 2)
        self.assertEqual(trips["pickup_zone_id"].tolist(), [161, 4])
        self.assertEqual(str(trips["pickup_at"].iloc[0]), "2026-03-10 08:00:00")

    def test_missing_column_raises_and_names_it(self):
        write_parquet(make_trips({}).drop(columns=["pickup_zone_id"]), self.path)

        with self.assertRaisesMessage(TripFileError, "PULocationID"):
            read_trips(self.path)

    def test_file_that_is_not_parquet_raises(self):
        self.path.write_text("not a parquet file")

        with self.assertRaises(TripFileError):
            read_trips(self.path)
