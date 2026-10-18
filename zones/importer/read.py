"""Reading the raw input files for the trip import."""

from pathlib import Path

import pandas as pd

ZONE_LOOKUP_CSV = Path(__file__).resolve().parent.parent / "data" / "taxi_zone_lookup.csv"


def read_zone_lookup(path=ZONE_LOOKUP_CSV):
    """Read the TLC taxi zone lookup as columns zone_id, name, borough.

    keep_default_na=False keeps the "N/A" text of zones 264 and 265
    instead of turning it into missing values.
    """
    lookup = pd.read_csv(
        path,
        usecols=["LocationID", "Zone", "Borough"],
        dtype={"LocationID": "int64"},
        keep_default_na=False,
    )
    lookup = lookup.rename(
        columns={"LocationID": "zone_id", "Zone": "name", "Borough": "borough"}
    )
    return lookup[["zone_id", "name", "borough"]]
