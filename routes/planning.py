"""Estimate when to leave for an arrival time from hourly route statistics."""

from math import floor

from zones.stats import route_stats


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
