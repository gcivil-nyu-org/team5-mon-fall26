"""Finding, and if needed downloading, the monthly TLC trip files."""

import argparse
import os
import re
import shutil
from datetime import datetime
from urllib.request import Request, urlopen

TRIP_URL = (
    "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{month}.parquet"
)
# CloudFront has rejected urllib's default User-Agent before.
USER_AGENT = "TaxiScope-NYC-import/1.0"
TIMEOUT_S = 60
CHUNK_BYTES = 1024 * 1024


def parse_month(value):
    """Check a --month value: exactly YYYY-MM with a real month."""
    # strptime's %m alone would also accept "2026-3".
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a month in YYYY-MM form")
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a valid month") from None
    return value


def repeated_months(months):
    """The months given more than once, sorted."""
    return sorted({month for month in months if months.count(month) > 1})


def trip_file_path(month, data_dir):
    return data_dir / f"yellow_tripdata_{month}.parquet"


def ensure_trip_file(month, data_dir):
    return ensure_file(TRIP_URL.format(month=month), trip_file_path(month, data_dir))


def ensure_file(url, path):
    """Return (path, downloaded). Downloads url to path only if path is
    missing.

    The download goes to "<name>.part" and is renamed when complete, so a
    download that was cut off is never mistaken for a full file.
    """
    if path.exists():
        return path, False

    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response, open(part, "wb") as out:
            shutil.copyfileobj(response, out, CHUNK_BYTES)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, path)
    return path, True
