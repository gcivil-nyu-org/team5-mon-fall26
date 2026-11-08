"""Query logic for the trip statistics API, kept out of the views so it
can be tested without HTTP."""

import json
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from statistics import median

from django.conf import settings

<<<<<<< HEAD
from .models import RideshareZoneHourStats, RouteHourStats, Zone, ZoneHourStats
=======
from .models import (
    RideshareRouteHourStats,
    RideshareZoneHourStats,
    RouteHourStats,
    Zone,
    ZoneHourStats,
)
>>>>>>> e1c45a9e7cd09c0e089d06bef0823ec23f11f3f8

STAT_FIELDS = ("fare_min", "fare_avg", "fare_max", "avg_duration_min")
RIDESHARE_STAT_FIELDS = STAT_FIELDS + ("avg_wait_min",)

NEIGHBORS_PATH = Path(__file__).resolve().parent / "data" / "zone_neighbors.json"


@lru_cache(maxsize=1)
def load_zone_neighbors():
    """zone_neighbors.json (US18) as {zone_id: [adjacent zone ids]}, read once."""
    with NEIGHBORS_PATH.open(encoding="utf-8") as f:
        return {int(zone_id): ids for zone_id, ids in json.load(f).items()}


def unknown_zone_ids(*zone_ids):
    """The ids among zone_ids (None is skipped) that are not in the zone table."""
    wanted = {zone_id for zone_id in zone_ids if zone_id is not None}
    known = set(
        Zone.objects.filter(zone_id__in=wanted).values_list("zone_id", flat=True)
    )
    return wanted - known


def route_stats(pickup_zone_id, dropoff_zone_id, day, hour):
    """Fare and duration stats for one day of week (Monday=0) and hour.

    With a dropoff zone, reads that route from route_hour_stats; without
    one, reads all trips from the pickup zone in zone_hour_stats. A cell
    with no row, or fewer than settings.MIN_TRIP_COUNT trips, gives
    enough_data False and None stats.
    """
    if dropoff_zone_id is None:
        rows = ZoneHourStats.objects.filter(zone_id=pickup_zone_id)
    else:
        rows = RouteHourStats.objects.filter(
            pickup_zone_id=pickup_zone_id, dropoff_zone_id=dropoff_zone_id
        )
    row = (
        rows.filter(day_of_week=day, hour=hour)
        .values("trip_count", *STAT_FIELDS)
        .first()
    )

    trip_count = row["trip_count"] if row else 0
    if trip_count < settings.MIN_TRIP_COUNT:
        return {
            "enough_data": False,
            "trip_count": trip_count,
            **dict.fromkeys(STAT_FIELDS),
        }
    return {"enough_data": True, **row}


def rideshare_route_stats(pickup_zone_id, dropoff_zone_id, day, hour):
    """Uber and Lyft (combined) fare, duration and wait for one day of week
    (Monday=0) and hour: the rideshare twin of route_stats (US28 #75).

    Same tables rule and same enough_data rule as route_stats: with a
    dropoff zone, rideshare_route_hour_stats for that route only; without
    one, rideshare_zone_hour_stats for all trips from the pickup zone.
    Fewer than settings.MIN_TRIP_COUNT trips gives enough_data False and
    None stats. avg_wait_min is also None when fewer than MIN_TRIP_COUNT
    of the trips have a valid wait (wait_count), even if the fare and
    duration have enough trips.
    """
    if dropoff_zone_id is None:
        rows = RideshareZoneHourStats.objects.filter(zone_id=pickup_zone_id)
    else:
        rows = RideshareRouteHourStats.objects.filter(
            pickup_zone_id=pickup_zone_id, dropoff_zone_id=dropoff_zone_id
        )
    row = (
        rows.filter(day_of_week=day, hour=hour)
        .values("trip_count", "wait_count", *RIDESHARE_STAT_FIELDS)
        .first()
    )

    trip_count = row["trip_count"] if row else 0
    if trip_count < settings.MIN_TRIP_COUNT:
        return {
            "enough_data": False,
            "trip_count": trip_count,
            **dict.fromkeys(RIDESHARE_STAT_FIELDS),
        }
    if row.pop("wait_count") < settings.MIN_TRIP_COUNT:
        row["avg_wait_min"] = None
    return {"enough_data": True, **row}


def route_windows(pickup_zone_id, dropoff_zone_id, day):
    """The hours of one day of week (Monday=0) ranked by average fare and
    by average duration, with the best and worst hour for each.

    Reads the same table as route_stats. Only hours with at least
    settings.MIN_TRIP_COUNT trips count. Best = cheapest and fastest hour,
    worst = most expensive and slowest; on a tie the earlier hour wins.
    Fewer than 2 such hours gives enough_data False and empty results.
    """
    if dropoff_zone_id is None:
        rows = ZoneHourStats.objects.filter(zone_id=pickup_zone_id)
    else:
        rows = RouteHourStats.objects.filter(
            pickup_zone_id=pickup_zone_id, dropoff_zone_id=dropoff_zone_id
        )
    hours = list(
        rows.filter(day_of_week=day, trip_count__gte=settings.MIN_TRIP_COUNT)
        .order_by("hour")
        .values("hour", "trip_count", "fare_avg", "avg_duration_min")
    )
    if len(hours) < 2:
        return {
            "enough_data": False,
            "hours": [],
            "by_fare": [],
            "by_duration": [],
            "best": None,
            "worst": None,
        }

    # hours is in hour order and sorts are stable, so ties keep the earlier hour.
    by_fare = sorted(hours, key=lambda h: h["fare_avg"])
    by_duration = sorted(hours, key=lambda h: h["avg_duration_min"])
    return {
        "enough_data": True,
        "hours": hours,
        "by_fare": [h["hour"] for h in by_fare],
        "by_duration": [h["hour"] for h in by_duration],
        "best": {"fare": by_fare[0], "duration": by_duration[0]},
        "worst": {
            "fare": max(hours, key=lambda h: h["fare_avg"]),
            "duration": max(hours, key=lambda h: h["avg_duration_min"]),
        },
    }


def surge_grid(zone_id):
    """US29 #76: the 7 x 24 "likely surge" grid for one pickup zone, from
    rideshare_zone_hour_stats (Uber and Lyft combined).

    An hour counts when it has at least settings.MIN_TRIP_COUNT trips and
    a fare per mile. The zone's typical fare per mile is the median of the
    counted hours across the week (each hour counts once, whatever its
    trips). A counted hour is a likely surge hour when its fare per mile
    is at least settings.SURGE_FARE_PER_MILE_RATIO times that median.
    Hours that do not count are never marked and have null fare per mile,
    wait and ratio; avg_wait_min is also null when fewer than
    MIN_TRIP_COUNT trips have a valid wait. No counted hour gives
    enough_data False and a null median.
    """
    minimum = settings.MIN_TRIP_COUNT
    cells = {
        (row["day_of_week"], row["hour"]): row
        for row in RideshareZoneHourStats.objects.filter(zone_id=zone_id).values(
            "day_of_week",
            "hour",
            "trip_count",
            "fare_per_mile",
            "avg_wait_min",
            "wait_count",
        )
    }
    counted = {
        key
        for key, row in cells.items()
        if row["trip_count"] >= minimum and row["fare_per_mile"] is not None
    }
    # Exact median (an even count can give half a cent); the rule uses it
    # as is, and only the value shown is rounded to the cent.
    typical = (
        median(cells[key]["fare_per_mile"] for key in counted) if counted else None
    )
    threshold = typical * settings.SURGE_FARE_PER_MILE_RATIO if counted else None

    grid = []
    for day in range(7):
        hours = []
        for hour in range(24):
            row = cells.get((day, hour))
            if (day, hour) not in counted:
                hours.append(
                    {
                        "trip_count": row["trip_count"] if row else None,
                        "fare_per_mile": None,
                        "avg_wait_min": None,
                        "surge_ratio": None,
                        "likely_surge": False,
                    }
                )
                continue
            fare_per_mile = row["fare_per_mile"]
            hours.append(
                {
                    "trip_count": row["trip_count"],
                    "fare_per_mile": fare_per_mile,
                    "avg_wait_min": (
                        row["avg_wait_min"] if row["wait_count"] >= minimum else None
                    ),
                    "surge_ratio": float(
                        (fare_per_mile / typical).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                    ),
                    "likely_surge": fare_per_mile >= threshold,
                }
            )
        grid.append(hours)

    return {
        "enough_data": bool(counted),
        "median_fare_per_mile": (
            typical.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if counted
            else None
        ),
        "surge_ratio_threshold": float(settings.SURGE_FARE_PER_MILE_RATIO),
        "min_trip_count": minimum,
        "surge": grid,
    }
