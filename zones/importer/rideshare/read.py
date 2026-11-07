"""Reading a monthly High Volume FHV file in batches.

A month has about 22 million trips, so the file is read a batch at a
time, with only the columns the import needs.
"""

import pyarrow
import pyarrow.compute as pc
import pyarrow.parquet as pq

from zones.importer.read import TripFileError

BATCH_SIZE = 262_144

# The TLC columns passed through, and our names for them. This is the
# only place that knows the raw names, so a renamed column is fixed here.
RAW_COLUMNS = {
    "request_datetime": "request_at",
    "pickup_datetime": "pickup_at",
    "dropoff_datetime": "dropoff_at",
    "PULocationID": "pickup_zone_id",
    "DOLocationID": "dropoff_zone_id",
    "trip_miles": "trip_miles",
    "base_passenger_fare": "base_passenger_fare",
    "tolls": "tolls",
    "bcf": "bcf",
    "sales_tax": "sales_tax",
    "congestion_surcharge": "congestion_surcharge",
    "airport_fee": "airport_fee",
    "cbd_congestion_fee": "cbd_congestion_fee",
}

# Text columns turned into booleans while still in Arrow, so pandas never
# holds millions of short strings.
LICENSE_COLUMN = "hvfhs_license_num"
SHARED_COLUMNS = {
    "shared_request_flag": "shared_request",
    "shared_match_flag": "shared_match",
}
UBER = "HV0003"
LYFT = "HV0005"

NEEDED_COLUMNS = [*RAW_COLUMNS, LICENSE_COLUMN, *SHARED_COLUMNS]
COLUMNS = [*RAW_COLUMNS.values(), "is_uber", "is_lyft", *SHARED_COLUMNS.values()]


def _equals(array, value):
    # A missing value is "not equal", never missing.
    return pc.fill_null(pc.equal(array, value), False)


def to_frame(batch):
    """One Arrow batch (or table) of raw columns -> a DataFrame of COLUMNS.

    A shared flag counts as shared unless it is exactly "N", so a missing
    flag fails the shared-ride rule, like any missing value.
    """
    columns = {ours: batch.column(raw) for raw, ours in RAW_COLUMNS.items()}
    license_num = batch.column(LICENSE_COLUMN)
    columns["is_uber"] = _equals(license_num, UBER)
    columns["is_lyft"] = _equals(license_num, LYFT)
    for raw, ours in SHARED_COLUMNS.items():
        columns[ours] = pc.invert(_equals(batch.column(raw), "N"))
    return pyarrow.table(columns).to_pandas()


def read_batches(path, batch_size=BATCH_SIZE):
    """Check the file, then return an iterator of DataFrames of at most
    batch_size trips each, with COLUMNS only.

    The file is checked when this is called, not when the first batch is
    read, so a bad file fails before any work starts.
    """
    try:
        parquet = pq.ParquetFile(path)
    except (OSError, pyarrow.ArrowInvalid) as exc:
        raise TripFileError(f"Cannot read {path}: {exc}") from exc

    names = parquet.schema_arrow.names
    missing = [column for column in NEEDED_COLUMNS if column not in names]
    if missing:
        raise TripFileError(f"{path} is missing columns: {', '.join(missing)}")

    batches = parquet.iter_batches(batch_size=batch_size, columns=NEEDED_COLUMNS)
    return (to_frame(batch) for batch in batches)
