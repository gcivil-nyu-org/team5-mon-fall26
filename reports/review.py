"""US24 #71: the rules that decide whether a fare report is shown or held."""

from datetime import datetime, time, timedelta

from zones.stats import route_stats
from zones.views import NYC_TZ

from .models import FareReport

DAILY_LIMIT = 10
MAX_AGE = timedelta(days=30)
# Held when the fare is below a third of the route's average, or above 3 times.
OUTLIER_FACTOR = 3


def review_status(pickup_zone_id, dropoff_zone_id, ride_at, taxi_fare):
    """VISIBLE or HELD, comparing the fare with the historical average for
    the route at the ride's day of week (Monday=0) and hour, in NYC time.

    A route with too few trips at that hour (route_stats' enough_data
    False) has nothing to compare with, so the report is shown.
    """
    local = ride_at.astimezone(NYC_TZ)
    stats = route_stats(pickup_zone_id, dropoff_zone_id, local.weekday(), local.hour)
    if not stats["enough_data"]:
        return FareReport.VISIBLE
    average = stats["fare_avg"]
    if taxi_fare * OUTLIER_FACTOR < average or taxi_fare > average * OUTLIER_FACTOR:
        return FareReport.HELD
    return FareReport.VISIBLE


def start_of_today(now):
    """Midnight today in NYC: the daily limit resets then."""
    local = now.astimezone(NYC_TZ)
    return datetime.combine(local.date(), time.min, tzinfo=NYC_TZ)


def reports_today(user, now):
    return FareReport.objects.filter(
        user=user, created_at__gte=start_of_today(now)
    ).count()
