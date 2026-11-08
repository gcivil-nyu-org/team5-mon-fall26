import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from zones.importer.read import TripFileError
from zones.importer.rideshare.read import (
    BATCH_SIZE,
    COLUMNS,
    NEEDED_COLUMNS,
    read_batches,
)
from zones.tests.rideshare_helpers import RAW_SCHEMA, write_trips


class ReadBatchesTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "fhvhv.parquet"

    def read_all(self, **kwargs):
        return list(read_batches(self.path, **kwargs))

    def test_default_batch_size(self):
        self.assertEqual(BATCH_SIZE, 262_144)

    def test_needed_columns_are_in_the_real_schema(self):
        self.assertTrue(set(NEEDED_COLUMNS) <= set(RAW_SCHEMA.names))

    def test_batches_have_only_our_renamed_columns(self):
        write_trips(self.path, {}, {"PULocationID": 4})

        (batch,) = self.read_all()

        self.assertEqual(list(batch.columns), COLUMNS)
        self.assertEqual(
            COLUMNS,
            [
                "request_at",
                "pickup_at",
                "dropoff_at",
                "pickup_zone_id",
                "dropoff_zone_id",
                "trip_miles",
                "base_passenger_fare",
                "tolls",
                "bcf",
                "sales_tax",
                "congestion_surcharge",
                "airport_fee",
                "cbd_congestion_fee",
                "is_uber",
                "is_lyft",
                "shared_request",
                "shared_match",
            ],
        )
        self.assertEqual(batch["pickup_zone_id"].tolist(), [161, 4])
        self.assertEqual(str(batch["pickup_at"].iloc[0]), "2026-03-10 08:00:00")
        self.assertEqual(str(batch["request_at"].iloc[0]), "2026-03-10 07:55:00")
        self.assertEqual(batch["sales_tax"].tolist(), [1.78, 1.78])

    def test_provider_becomes_booleans(self):
        write_trips(
            self.path,
            {"hvfhs_license_num": "HV0003"},
            {"hvfhs_license_num": "HV0005"},
            {"hvfhs_license_num": "HV0004"},
            {"hvfhs_license_num": None},
        )

        (batch,) = self.read_all()

        self.assertEqual(batch["is_uber"].tolist(), [True, False, False, False])
        self.assertEqual(batch["is_lyft"].tolist(), [False, True, False, False])
        self.assertEqual(str(batch["is_uber"].dtype), "bool")
        self.assertEqual(str(batch["is_lyft"].dtype), "bool")

    def test_shared_flags_become_booleans(self):
        # Only "N" means not shared, so a missing flag fails the shared rule.
        write_trips(
            self.path,
            {"shared_request_flag": "N", "shared_match_flag": "N"},
            {"shared_request_flag": "Y", "shared_match_flag": "N"},
            {"shared_request_flag": "N", "shared_match_flag": "Y"},
            {"shared_request_flag": None, "shared_match_flag": None},
        )

        (batch,) = self.read_all()

        self.assertEqual(batch["shared_request"].tolist(), [False, True, False, True])
        self.assertEqual(batch["shared_match"].tolist(), [False, False, True, True])
        self.assertEqual(str(batch["shared_request"].dtype), "bool")
        self.assertEqual(str(batch["shared_match"].dtype), "bool")

    def test_reads_in_batches_of_the_given_size(self):
        write_trips(self.path, *[{"PULocationID": zone} for zone in range(1, 6)])

        batches = self.read_all(batch_size=2)

        self.assertEqual([len(batch) for batch in batches], [2, 2, 1])
        self.assertEqual(
            [zone for batch in batches for zone in batch["pickup_zone_id"]],
            [1, 2, 3, 4, 5],
        )

    def test_unneeded_column_may_be_missing(self):
        write_trips(self.path, {}, drop=["driver_pay", "on_scene_datetime"])

        (batch,) = self.read_all()

        self.assertEqual(len(batch), 1)

    def test_missing_columns_raise_and_name_them(self):
        write_trips(self.path, {}, drop=["airport_fee", "cbd_congestion_fee"])

        with self.assertRaisesMessage(
            TripFileError, "missing columns: airport_fee, cbd_congestion_fee"
        ):
            read_batches(self.path)

    def test_missing_flag_column_raises(self):
        write_trips(self.path, {}, drop=["shared_match_flag"])

        with self.assertRaisesMessage(TripFileError, "shared_match_flag"):
            read_batches(self.path)

    def test_file_that_is_not_parquet_raises(self):
        self.path.write_text("not a parquet file")

        with self.assertRaises(TripFileError):
            read_batches(self.path)

    def test_missing_file_raises(self):
        with self.assertRaises(TripFileError):
            read_batches(self.path)
