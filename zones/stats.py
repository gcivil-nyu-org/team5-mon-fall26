"""Query logic for the trip statistics API, kept out of the views so it
can be tested without HTTP."""

from django.conf import settings

from .models import RouteHourStats, Zone, ZoneHourStats

STAT_FIELDS = ("fare_min", "fare_avg", "fare_max", "avg_duration_min")


def unknown_zone_ids(*zone_ids):
    """The ids among zone_ids (None is skipped) that are not in the zone table."""
    wanted = {zone_id for zone_id in zone_ids if zone_id is not None}
    known = set(Zone.objects.filter(zone_id__in=wanted).values_list("zone_id", flat=True))
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
    row = rows.filter(day_of_week=day, hour=hour).values("trip_count", *STAT_FIELDS).first()

    trip_count = row["trip_count"] if row else 0
    if trip_count < settings.MIN_TRIP_COUNT:
        return {"enough_data": False, "trip_count": trip_count, **dict.fromkeys(STAT_FIELDS)}
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
        return {"enough_data": False, "hours": [], "by_fare": [], "by_duration": [],
                "best": None, "worst": None}

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
