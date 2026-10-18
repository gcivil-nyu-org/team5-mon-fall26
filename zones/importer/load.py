"""Writing zones and statistics to the database.

load_all() runs everything in one transaction: if any step fails, the
old zones and statistics stay as they were.
"""

from itertools import batched

from django.db import connection, transaction

from zones.importer.aggregate import average_cents_to_decimal, cents_to_decimal
from zones.models import RouteHourStats, Zone, ZoneHourStats

# 5000 rows x 9 fields stays under PostgreSQL's 65,535 parameters per query.
BATCH_SIZE = 5000


def upsert_zones(lookup):
    """Insert or update every zone from the lookup. Never deletes, because
    deleting a zone would cascade to its statistics."""
    zones = [
        Zone(zone_id=int(row.zone_id), name=row.name, borough=row.borough)
        for row in lookup.itertuples(index=False)
    ]
    Zone.objects.bulk_create(
        zones,
        update_conflicts=True,
        unique_fields=["zone_id"],
        update_fields=["name", "borough"],
    )
    return len(zones)


def _stat_fields(row):
    return {
        "day_of_week": int(row.day_of_week),
        "hour": int(row.hour),
        "trip_count": int(row.trip_count),
        "avg_duration_min": float(row.avg_duration_min),
        "fare_min": cents_to_decimal(row.fare_min_cents),
        "fare_avg": average_cents_to_decimal(row.fare_sum_cents, row.trip_count),
        "fare_max": cents_to_decimal(row.fare_max_cents),
    }


def _zone_stat(row):
    return ZoneHourStats(zone_id=int(row.pickup_zone_id), **_stat_fields(row))


def _route_stat(row):
    return RouteHourStats(
        pickup_zone_id=int(row.pickup_zone_id),
        dropoff_zone_id=int(row.dropoff_zone_id),
        **_stat_fields(row),
    )


def _bulk_insert(model, build, stats, batch_size):
    # Model objects are built one batch at a time, so 1.3M route rows
    # never sit in memory as model instances all at once.
    for rows in batched(stats.itertuples(index=False), batch_size):
        model.objects.bulk_create([build(row) for row in rows])
    return len(stats)


def replace_stats(zone_stats, route_stats, batch_size=BATCH_SIZE):
    """Empty both statistics tables and fill them from the final stats.

    DELETE (not TRUNCATE) lets the API keep reading the old rows until
    the surrounding transaction commits.
    """
    ZoneHourStats.objects.all().delete()
    RouteHourStats.objects.all().delete()
    n_zone = _bulk_insert(ZoneHourStats, _zone_stat, zone_stats, batch_size)
    n_route = _bulk_insert(RouteHourStats, _route_stat, route_stats, batch_size)
    return n_zone, n_route


def analyze_stats():
    """Refresh PostgreSQL's planner statistics after a full replacement."""
    with connection.cursor() as cursor:
        for model in (ZoneHourStats, RouteHourStats):
            cursor.execute(f"ANALYZE {connection.ops.quote_name(model._meta.db_table)}")


def load_all(lookup, zone_stats, route_stats):
    """Upsert zones and replace both statistics tables in one transaction.

    Returns (zones, zone cells, route cells) written.
    """
    with transaction.atomic():
        n_zones = upsert_zones(lookup)
        n_zone, n_route = replace_stats(zone_stats, route_stats)
    analyze_stats()
    return n_zones, n_zone, n_route
