"""Writing the rideshare statistics to the database with COPY.

load_rideshare() upserts the zones and replaces both rideshare tables in
one transaction: if any step fails, the old zones and rideshare rows stay
as they were. The taxi tables are never touched.
"""

from django.db import connection, transaction

from zones.importer.aggregate import ratio_to_cents_decimal
from zones.importer.load import analyze_stats, stat_fields, upsert_zones
from zones.models import RideshareRouteHourStats, RideshareZoneHourStats

# Statistics columns in the order _stat_values() gives them.
STAT_COLUMNS = [
    "day_of_week",
    "hour",
    "trip_count",
    "avg_duration_min",
    "fare_min",
    "fare_avg",
    "fare_max",
    "avg_wait_min",
    "wait_count",
    "fare_per_mile",
]
ZONE_COLUMNS = ["zone_id", *STAT_COLUMNS]
ROUTE_COLUMNS = ["pickup_zone_id", "dropoff_zone_id", *STAT_COLUMNS]

TABLES = (RideshareZoneHourStats, RideshareRouteHourStats)


def _stat_values(row):
    """One finalize() row as values for STAT_COLUMNS: the taxi columns,
    rounded the taxi way, then wait and fare per mile."""
    wait_count = int(row.wait_count)
    miles = int(row.miles_sum_hundredths)
    return (
        *stat_fields(row).values(),
        float(row.avg_wait_min) if wait_count else None,
        wait_count,
        # Fare cents / mile hundredths is dollars per mile. Null when the
        # miles rounded to 0 hundredths (trips under 0.005 miles).
        ratio_to_cents_decimal(row.fare_sum_cents, miles) if miles else None,
    )


def _zone_row(row):
    return (int(row.pickup_zone_id), *_stat_values(row))


def _route_row(row):
    return (int(row.pickup_zone_id), int(row.dropoff_zone_id), *_stat_values(row))


def copy_rows(model, columns, rows):
    """Write rows (tuples in columns order) with one COPY. Returns the
    number of rows."""
    quote = connection.ops.quote_name
    sql = "COPY {} ({}) FROM STDIN".format(
        quote(model._meta.db_table), ", ".join(quote(c) for c in columns)
    )
    count = 0
    with connection.cursor() as cursor, cursor.copy(sql) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def replace_rideshare_stats(zone_stats, route_stats):
    """Empty both rideshare tables and fill them from the final stats.

    DELETE (not TRUNCATE), as for taxis: readers keep the old rows until
    the surrounding transaction commits.
    """
    for model in TABLES:
        model.objects.all().delete()
    n_zone = copy_rows(
        RideshareZoneHourStats,
        ZONE_COLUMNS,
        map(_zone_row, zone_stats.itertuples(index=False)),
    )
    n_route = copy_rows(
        RideshareRouteHourStats,
        ROUTE_COLUMNS,
        map(_route_row, route_stats.itertuples(index=False)),
    )
    return n_zone, n_route


def load_rideshare(lookup, zone_stats, route_stats):
    """Upsert zones and replace both rideshare tables in one transaction,
    then ANALYZE them once the new rows are committed.

    Returns (zones, zone cells, route cells) written.
    """
    with transaction.atomic():
        n_zones = upsert_zones(lookup)
        n_zone, n_route = replace_rideshare_stats(zone_stats, route_stats)
    analyze_stats(TABLES)
    return n_zones, n_zone, n_route
