import io
import tempfile
from pathlib import Path
from unittest import mock
from urllib.error import URLError

from django.test import SimpleTestCase

from zones.importer.rideshare.download import (
    RIDESHARE_URL,
    ensure_rideshare_file,
    rideshare_file_path,
)


class FakeResponse(io.BytesIO):
    """A urlopen() response: a readable, closable byte stream."""


class EnsureRideshareFileTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "raw"

    def test_file_name(self):
        self.assertEqual(
            rideshare_file_path("2026-03", self.data_dir),
            self.data_dir / "fhvhv_tripdata_2026-03.parquet",
        )

    def test_url(self):
        self.assertEqual(
            RIDESHARE_URL.format(month="2026-03"),
            "https://d37ci6vzurychx.cloudfront.net/trip-data/"
            "fhvhv_tripdata_2026-03.parquet",
        )

    def test_existing_file_is_not_downloaded(self):
        self.data_dir.mkdir()
        path = rideshare_file_path("2026-03", self.data_dir)
        path.write_bytes(b"already here")

        with mock.patch("zones.importer.download.urlopen") as urlopen:
            result = ensure_rideshare_file("2026-03", self.data_dir)

        self.assertEqual(result, (path, False))
        urlopen.assert_not_called()
        self.assertEqual(path.read_bytes(), b"already here")

    def test_missing_file_is_downloaded_from_the_rideshare_url(self):
        with mock.patch(
            "zones.importer.download.urlopen",
            return_value=FakeResponse(b"parquet bytes"),
        ) as urlopen:
            path, downloaded = ensure_rideshare_file("2026-04", self.data_dir)

        self.assertTrue(downloaded)
        self.assertEqual(path, self.data_dir / "fhvhv_tripdata_2026-04.parquet")
        self.assertEqual(path.read_bytes(), b"parquet bytes")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, RIDESHARE_URL.format(month="2026-04"))
        self.assertTrue(request.get_header("User-agent"))
        self.assertEqual(sorted(p.name for p in self.data_dir.iterdir()), [path.name])

    def test_failed_download_leaves_no_file(self):
        with mock.patch(
            "zones.importer.download.urlopen", side_effect=URLError("no network")
        ):
            with self.assertRaises(URLError):
                ensure_rideshare_file("2026-03", self.data_dir)

        self.assertEqual(list(self.data_dir.iterdir()), [])
