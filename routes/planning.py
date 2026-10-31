"""Estimate when to leave for an arrival time from hourly route statistics."""

from math import floor

from django.conf import settings

from zones.models import RouteHourStats
from zones.stats import load_zone_neighbors, route_stats


def leave_by(pickup, dropoff, day, arrive_hour, arrive_minute):
    """Use the arrival hour, then refine once using the estimated departure hour."""
    arrival_minutes = arrive_hour * 60 + arrive_minute
    arrival_stats = route_stats(pickup, dropoff, day, arrive_hour)
    if not arrival_stats["enough_data"]:
        return _not_enough(arrival_stats)

    first_departure = arrival_minutes - arrival_stats["avg_duration_min"]
    first_day = (day + floor(first_departure / 1440)) % 7
    first_hour = floor(first_departure / 60) % 24
    departure_stats = route_stats(pickup, dropoff, first_day, first_hour)
    if not departure_stats["enough_data"]:
        return _not_enough(departure_stats)

    departure_minutes = (
        floor((arrival_minutes - departure_stats["avg_duration_min"]) / 15) * 15
    )
    leave_day = (day + floor(departure_minutes / 1440)) % 7
    leave_clock = departure_minutes % 1440
    return {
        "enough_data": True,
        "leave_day": leave_day,
        "leave": f"{leave_clock // 60:02d}:{leave_clock % 60:02d}",
        "trip_count": departure_stats["trip_count"],
        "avg_duration_min": departure_stats["avg_duration_min"],
        "fare_avg": departure_stats["fare_avg"],
    }


def _not_enough(stats):
    return {
        "enough_data": False,
        "leave_day": None,
        "leave": None,
        "trip_count": stats["trip_count"],
        "avg_duration_min": None,
        "fare_avg": None,
    }


WEEK_MINUTES = 7 * 24 * 60
WINDOW_HOURS = 3


def _week_clock(minutes):
    """Minutes since Monday 00:00 -> (day Monday=0, "HH:MM"), wrapping the week."""
    minutes %= WEEK_MINUTES
    return minutes // 1440, f"{minutes % 1440 // 60:02d}:{minutes % 60:02d}"


def cheapest_in_window(pickup, dropoff, day, start_hour, start_minute):
    """US16: the cheapest of the 3 one-hour slots starting at the start hour.

    The slots are the start hour and the next 2 hours, continuing into the
    next day after midnight (Sunday wraps to Monday). Only slots with at
    least settings.MIN_TRIP_COUNT trips count; the lowest average fare wins
    and a tie goes to the earlier slot. The suggested departure is the start
    time if the first slot is cheapest, otherwise the start of the cheapest
    hour. Expected arrival = departure + that hour's average duration.
    """
    start = day * 1440 + start_hour * 60 + start_minute
    hours = []
    for i in range(WINDOW_HOURS):
        slot_day, slot_clock = _week_clock(day * 1440 + (start_hour + i) * 60)
        slot_hour = int(slot_clock[:2])
        stats = route_stats(pickup, dropoff, slot_day, slot_hour)
        hours.append(
            {
                "day": slot_day,
                "hour": slot_hour,
                "enough_data": stats["enough_data"],
                "trip_count": stats["trip_count"],
                "fare_avg": stats["fare_avg"],
                "avg_duration_min": stats["avg_duration_min"],
            }
        )

    usable = [i for i, h in enumerate(hours) if h["enough_data"]]
    if not usable:
        return {
            "enough_data": False,
            "hours": hours,
            "cheapest": None,
            "leave_day": None,
            "leave": None,
            "arrive_day": None,
            "arrive": None,
            "avg_duration_min": None,
            "fare_avg": None,
        }

    # min() keeps the first of equal values, so a tie goes to the earlier hour.
    best = min(usable, key=lambda i: hours[i]["fare_avg"])
    leave = start if best == 0 else day * 1440 + (start_hour + best) * 60
    arrive = leave + round(hours[best]["avg_duration_min"])
    leave_day, leave_clock = _week_clock(leave)
    arrive_day, arrive_clock = _week_clock(arrive)
    return {
        "enough_data": True,
        "hours": hours,
        "cheapest": best,
        "leave_day": leave_day,
        "leave": leave_clock,
        "arrive_day": arrive_day,
        "arrive": arrive_clock,
        "avg_duration_min": hours[best]["avg_duration_min"],
        "fare_avg": hours[best]["fare_avg"],
    }


DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def plan_result(plan):
    """US17: recalculate a saved plan's result from the current statistics.

    Nothing about the result is stored, so it always reflects the latest
    import. Adds display labels for the plan pages.
    """
    pickup, dropoff = plan.pickup_zone_id, plan.dropoff_zone_id
    hour, minute = plan.time.hour, plan.time.minute
    if plan.mode == plan.ARRIVE_BY:
        result = leave_by(pickup, dropoff, plan.day_of_week, hour, minute)
    else:
        result = cheapest_in_window(pickup, dropoff, plan.day_of_week, hour, minute)
        for slot in result["hours"]:
            clock = f"{slot['hour']:02d}"
            slot["label"] = f"{DAY_NAMES[slot['day']][:3]} {clock}:00–{clock}:59"
    result["mode"] = plan.mode
    if result["enough_data"]:
        result["leave_label"] = f"{DAY_NAMES[result['leave_day']]} {result['leave']}"
        if result.get("arrive") is not None:
            result["arrive_label"] = (
                f"{DAY_NAMES[result['arrive_day']]} {result['arrive']}"
            )
    return result


NEARBY_LIMIT = 3


def cheaper_nearby(pickup, dropoff, day, hour):
    """US19: up to NEARBY_LIMIT zones adjacent to the pickup where the same
    trip (same dropoff, day and hour) has a lower average fare.

    Both routes need settings.MIN_TRIP_COUNT trips. The dropoff zone is never
    suggested. Biggest saving first; on a tie, the lower zone id.
    neighbor_count is the number of adjacent zones considered, so 0 means
    the pickup borders no other zone (an island).
    """
    candidates = [
        zone_id
        for zone_id in load_zone_neighbors().get(pickup, [])
        if zone_id != dropoff
    ]
    stats = route_stats(pickup, dropoff, day, hour)
    current = {
        "trip_count": stats["trip_count"],
        "fare_avg": stats["fare_avg"],
        "avg_duration_min": stats["avg_duration_min"],
    }
    if not stats["enough_data"] or not candidates:
        return {
            "enough_data": stats["enough_data"],
            "current": current,
            "neighbor_count": len(candidates),
            "suggestions": [],
        }

    rows = (
        RouteHourStats.objects.filter(
            pickup_zone_id__in=candidates,
            dropoff_zone_id=dropoff,
            day_of_week=day,
            hour=hour,
            trip_count__gte=settings.MIN_TRIP_COUNT,
            fare_avg__lt=stats["fare_avg"],
        )
        .order_by("fare_avg", "pickup_zone_id")
        .values(
            "pickup_zone_id",
            "pickup_zone__name",
            "pickup_zone__borough",
            "trip_count",
            "fare_avg",
            "avg_duration_min",
        )[:NEARBY_LIMIT]
    )
    return {
        "enough_data": True,
        "current": current,
        "neighbor_count": len(candidates),
        "suggestions": [
            {
                "zone_id": row["pickup_zone_id"],
                "name": row["pickup_zone__name"],
                "borough": row["pickup_zone__borough"],
                "trip_count": row["trip_count"],
                "fare_avg": row["fare_avg"],
                "avg_duration_min": row["avg_duration_min"],
                "saving": stats["fare_avg"] - row["fare_avg"],
            }
            for row in rows
        ],
    }
