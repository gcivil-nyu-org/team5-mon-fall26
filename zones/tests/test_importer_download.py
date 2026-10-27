import argparse
import io
import tempfile
from pathlib import Path
from unittest import mock
from urllib.error import URLError

from django.test import SimpleTestCase

from zones.importer.download import (
    TRIP_URL,
    ensure_trip_file,
    parse_month,
    trip_file_path,
)


class ParseMonthTests(SimpleTestCase):
    def test_accepts_yyyy_mm(self):
        self.assertEqual(parse_month("2026-03"), "2026-03")
        self.assertEqual(parse_month("2026-12"), "2026-12")

    def test_rejects_anything_else(self):
        for value in [
            "2026-3",
            "2026-003",
            "2026-00",
            "2026-13",
            "2026-03-01",
            " 2026-03",
            "March",
            "",
        ]:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    parse_month(value)


class FakeResponse(io.BytesIO):
    """A urlopen() response: a readable, closable byte stream."""


class BrokenResponse(io.RawIOBase):
    """Sends a few bytes, then the connection drops."""

    def __init__(self):
        self.sent = False

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.sent:
            raise URLError("connection reset")
        self.sent = True
        buffer[:3] = b"PAR"
        return 3


class EnsureTripFileTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "raw"

    def test_file_name(self):
        self.assertEqual(
            trip_file_path("2026-03", self.data_dir),
            self.data_dir / "yellow_tripdata_2026-03.parquet",
        )

    def test_existing_file_is_not_downloaded(self):
        self.data_dir.mkdir()
        path = trip_file_path("2026-03", self.data_dir)
        path.write_bytes(b"already here")

        with mock.patch("zones.importer.download.urlopen") as urlopen:
            result = ensure_trip_file("2026-03", self.data_dir)

        self.assertEqual(result, (path, False))
        urlopen.assert_not_called()
        self.assertEqual(path.read_bytes(), b"already here")

    def test_missing_file_is_downloaded(self):
        with mock.patch(
            "zones.importer.download.urlopen",
            return_value=FakeResponse(b"parquet bytes"),
        ) as urlopen:
            path, downloaded = ensure_trip_file("2026-03", self.data_dir)

        self.assertTrue(downloaded)
        self.assertEqual(path.read_bytes(), b"parquet bytes")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, TRIP_URL.format(month="2026-03"))
        self.assertEqual(
            request.full_url,
            "https://d37ci6vzurychx.cloudfront.net/trip-data/"
            "yellow_tripdata_2026-03.parquet",
        )
        self.assertTrue(request.get_header("User-agent"))
        self.assertEqual(sorted(p.name for p in self.data_dir.iterdir()), [path.name])

    def test_broken_download_leaves_no_file(self):
        with mock.patch(
            "zones.importer.download.urlopen", return_value=BrokenResponse()
        ):
            with self.assertRaises(URLError):
                ensure_trip_file("2026-03", self.data_dir)

        self.assertEqual(list(self.data_dir.iterdir()), [])

    def test_failed_request_leaves_no_file(self):
        with mock.patch(
            "zones.importer.download.urlopen", side_effect=URLError("no network")
        ):
            with self.assertRaises(URLError):
                ensure_trip_file("2026-03", self.data_dir)

        self.assertFalse(trip_file_path("2026-03", self.data_dir).exists())
