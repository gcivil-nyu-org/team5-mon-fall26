"""Finding, and if needed downloading, the monthly High Volume FHV files."""

from zones.importer.download import ensure_file

RIDESHARE_URL = (
    "https://d37ci6vzurychx.cloudfront.net/trip-data/fhvhv_tripdata_{month}.parquet"
)


def rideshare_file_path(month, data_dir):
    return data_dir / f"fhvhv_tripdata_{month}.parquet"


def ensure_rideshare_file(month, data_dir):
    """Return (path, downloaded), downloading the month only if missing."""
    return ensure_file(
        RIDESHARE_URL.format(month=month), rideshare_file_path(month, data_dir)
    )
