"""US32 #94: find open shared rides on a route like mine, around my time."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.utils import timezone

from accounts.display_name import display_name_of
from zones.stats import load_zone_neighbors
from zones.views import NYC_TZ

from .models import RidePost

TIME_WINDOW = timedelta(hours=1)
SAME_ROUTE = "Same route"
NEARBY_PICKUP = "Nearby pickup"
NEARBY_DROPOFF = "Nearby dropoff"
NEARBY_BOTH = "Nearby pickup and dropoff"


@dataclass
class Match:
    post: RidePost
    exact: bool
    label: str
    owner_name: str


def _with_neighbors(zone_id):
    return {zone_id, *load_zone_neighbors().get(zone_id, [])}


def _label(post, pickup_id, dropoff_id):
    same_pickup = post.pickup_zone_id == pickup_id
    same_dropoff = post.dropoff_zone_id == dropoff_id
    if same_pickup and same_dropoff:
        return SAME_ROUTE
    if same_dropoff:
        return NEARBY_PICKUP
    if same_pickup:
        return NEARBY_DROPOFF
    return NEARBY_BOTH


def find_rides(user, pickup, dropoff, day, at_time=None, now=None):
    """Open posts by other riders whose pickup is the same zone as `pickup`
    or adjacent to it (zone_neighbors.json, US18), whose dropoff is the same
    as or adjacent to `dropoff`, departing on `day` (New York time) and, with
    `at_time`, within 1 hour of it. Same route first, then by departure."""
    now = now or timezone.now()
    posts = RidePost.objects.open(now).filter(
        pickup_zone_id__in=_with_neighbors(pickup.pk),
        dropoff_zone_id__in=_with_neighbors(dropoff.pk),
        departure_at__gte=datetime.combine(day, time.min, NYC_TZ),
        departure_at__lt=datetime.combine(day + timedelta(days=1), time.min, NYC_TZ),
    )
    if at_time is not None:
        target = datetime.combine(day, at_time, NYC_TZ)
        posts = posts.filter(
            departure_at__gte=target - TIME_WINDOW,
            departure_at__lte=target + TIME_WINDOW,
        )
    posts = posts.exclude(owner=user).select_related(
        "owner__profile", "pickup_zone", "dropoff_zone"
    )
    matches = []
    for post in posts:
        label = _label(post, pickup.pk, dropoff.pk)
        matches.append(
            Match(post, label == SAME_ROUTE, label, display_name_of(post.owner))
        )
    matches.sort(key=lambda m: (not m.exact, m.post.departure_at, m.post.pk))
    return matches


def date_for_day(day, now=None):
    """The trip summary's day (Monday=0 .. Sunday=6) as the next date on that
    weekday in New York, today included. None for anything else."""
    try:
        weekday = int(day)
    except (TypeError, ValueError):
        return None
    if not 0 <= weekday <= 6:
        return None
    today = (now or timezone.now()).astimezone(NYC_TZ).date()
    return today + timedelta(days=(weekday - today.weekday()) % 7)
