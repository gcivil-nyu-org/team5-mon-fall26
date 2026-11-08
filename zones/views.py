import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Zone, ZoneHourStats
from .stats import (
    rideshare_route_stats,
    route_stats,
    route_windows,
    surge_grid,
    unknown_zone_ids,
)

ZONE_SHAPES_PATH = Path(__file__).resolve().parent / "data" / "taxi_zones.geojson"

# Trip times are recorded in NYC local time, so "now" must be NYC time too.
NYC_TZ = ZoneInfo("America/New_York")

# Largest value of a PostgreSQL integer column such as zone.zone_id.
MAX_ZONE_ID = 2**31 - 1


def map_view(request, saved_route=None):
    """The main page: a Leaflet map of NYC taxi zones colored by demand."""
    now = datetime.now(NYC_TZ)
    return render(
        request,
        "zones/map.html",
        {
            "current_day": now.weekday(),
            "current_hour": now.hour,
            "saved_route": saved_route,
            # US29 #76: the surge legend states the rule's numbers.
            "surge_ratio": settings.SURGE_FARE_PER_MILE_RATIO,
            "min_trip_count": settings.MIN_TRIP_COUNT,
        },
    )


LINK_NOT_ON_MAP = "A zone in the link isn't on the map, so it was left out."
LINK_SAME_ZONE = "The link named the same zone for A and B, so B was left out."


def _link_zone(request, key):
    """(zone id or None, valid) for ?a= or ?b= on the compare page. Missing
    or empty is valid; anything that is not a zone drawn on the map is not."""
    raw = request.GET.get(key, "")
    if raw == "":
        return None, True
    zone_id = _parse_int(raw, 1, MAX_ZONE_ID)
    if zone_id in shape_zone_ids():
        return zone_id, True
    return None, False


@require_GET
def compare_view(request, saved_comparison=None):
    """US22 #69: compare two zones side by side, on its own public page.

    /compare/?a=&b=&day=&hour= starts with those zones and that time. Ids
    that are not zones on the map are left out with a message; a day or
    hour out of range falls back to the current NYC day or hour. An opened
    saved comparison (US23 #70, ownership checked by the caller) gives the
    zones instead of a= and b=.
    """
    now = datetime.now(NYC_TZ)
    day = _parse_int(request.GET.get("day"), 0, 6)
    hour = _parse_int(request.GET.get("hour"), 0, 23)
    start_a, valid_a = _link_zone(request, "a")
    start_b, valid_b = _link_zone(request, "b")
    messages = []
    if saved_comparison is not None:
        start_a, start_b = saved_comparison.zone_a_id, saved_comparison.zone_b_id
    elif not (valid_a and valid_b):
        messages.append(LINK_NOT_ON_MAP)
    if start_a is not None and start_a == start_b:
        start_b = None
        messages.append(LINK_SAME_ZONE)
    return render(
        request,
        "zones/compare.html",
        {
            "current_day": now.weekday() if day is None else day,
            "current_hour": now.hour if hour is None else hour,
            "min_trip_count": settings.MIN_TRIP_COUNT,
            "start_a": start_a,
            "start_b": start_b,
            "link_message": " ".join(messages),
            "saved_comparison": saved_comparison,
            # "or choose from list": zones on the map, borough then name.
            "zone_choices": Zone.objects.filter(zone_id__in=shape_zone_ids()).order_by(
                "borough", "name"
            ),
        },
    )


@lru_cache(maxsize=1)
def load_zone_shapes():
    """Read the zone GeoJSON once and keep it in memory."""
    with ZONE_SHAPES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def shape_zone_ids():
    """Ids of the zones drawn on the map (1..263; 264 and 265 have no shape)."""
    return frozenset(
        feature["properties"]["LocationID"]
        for feature in load_zone_shapes()["features"]
    )


def _parse_int(value, low, high):
    """Return value as an int in [low, high], or None if it is not valid."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


@require_GET
def zones_api(request):
    """GET /api/zones?day=&hour=

    Every taxi zone as GeoJSON, with its trip volume for that day of week
    (Monday=0 .. Sunday=6) and hour (0-23). Defaults to the current NYC
    day and hour. Zones with no trips in that hour get trip_count 0.
    """
    now = datetime.now(NYC_TZ)
    day = _parse_int(request.GET.get("day", now.weekday()), 0, 6)
    hour = _parse_int(request.GET.get("hour", now.hour), 0, 23)
    if day is None or hour is None:
        return JsonResponse(
            {"error": "day must be 0-6 (Monday=0) and hour must be 0-23"},
            status=400,
        )

    names = {z.zone_id: (z.name, z.borough) for z in Zone.objects.all()}
    stats = {
        row["zone_id"]: row
        for row in ZoneHourStats.objects.filter(day_of_week=day, hour=hour).values(
            "zone_id",
            "trip_count",
            "avg_duration_min",
            "fare_min",
            "fare_avg",
            "fare_max",
        )
    }

    features = []
    for shape in load_zone_shapes()["features"]:
        props = shape["properties"]
        zone_id = props["LocationID"]
        name, borough = names.get(zone_id, (props["zone"], props["borough"]))
        zone_stats = stats.get(zone_id)
        features.append(
            {
                "type": "Feature",
                "geometry": shape["geometry"],
                "properties": {
                    "zone_id": zone_id,
                    "name": name,
                    "borough": borough,
                    "trip_count": zone_stats["trip_count"] if zone_stats else 0,
                    "avg_duration_min": (
                        zone_stats["avg_duration_min"] if zone_stats else None
                    ),
                    "fare_min": zone_stats["fare_min"] if zone_stats else None,
                    "fare_avg": zone_stats["fare_avg"] if zone_stats else None,
                    "fare_max": zone_stats["fare_max"] if zone_stats else None,
                },
            }
        )

    return JsonResponse(
        {"type": "FeatureCollection", "day": day, "hour": hour, "features": features}
    )


@require_GET
def heatmap_api(request, zone_id):
    """GET /api/zones/:id/heatmap

    Returns a 7x24 grid (7 days x 24 hours) of trip volume and average
    trip duration for the zone. Cells with no data have null values.
    """
    try:
        zone = Zone.objects.get(zone_id=zone_id)
    except Zone.DoesNotExist:
        return JsonResponse({"error": "Zone not found"}, status=404)

    # Fetch all stats for this zone
    stats = ZoneHourStats.objects.filter(zone=zone).values(
        "day_of_week", "hour", "trip_count", "avg_duration_min"
    )
    stats_dict = {(s["day_of_week"], s["hour"]): s for s in stats}

    # Build 7x24 grid with null for missing cells
    heatmap = []
    for day in range(7):
        day_data = []
        for hour in range(24):
            cell = stats_dict.get((day, hour))
            day_data.append(
                {
                    "trip_count": cell["trip_count"] if cell else None,
                    "avg_duration_min": cell["avg_duration_min"] if cell else None,
                }
            )
        heatmap.append(day_data)

    return JsonResponse(
        {
            "zone_id": zone_id,
            "zone_name": zone.name,
            "borough": zone.borough,
            "heatmap": heatmap,
        }
    )


@require_GET
def surge_api(request, zone_id):
    """GET /api/zones/:id/surge

    US29 #76: for each of the 7 x 24 day/hour cells of the pickup zone,
    whether it is a likely Uber/Lyft surge hour, with its fare per mile,
    average wait and ratio to the zone's median hour. The rule is in
    zones.stats.surge_grid and docs/decisions.md. Unknown zone: 404, as
    for the heatmap.
    """
    try:
        zone = Zone.objects.get(zone_id=zone_id)
    except Zone.DoesNotExist:
        return JsonResponse({"error": "Zone not found"}, status=404)

    return JsonResponse(
        {
            "zone_id": zone_id,
            "zone_name": zone.name,
            "borough": zone.borough,
            **surge_grid(zone_id),
        }
    )


ROUTE_QUERY_ERROR = (
    "from must be a known zone id; to, if given, must be a known zone id; "
    "day must be 0-6 (Monday=0) and hour must be 0-23"
)


def _route_query(request):
    """The from, to, day and hour of a /api/routes-style request, as
    (pickup, dropoff, day, hour), or None if any of them is invalid.

    `from` is required; `to` is optional (missing or empty gives None);
    day (Monday=0 .. Sunday=6) and hour (0-23) default to the current NYC
    day and hour. Both zone ids must be in the zone table.
    """
    now = datetime.now(NYC_TZ)
    pickup = _parse_int(request.GET.get("from"), 1, MAX_ZONE_ID)
    raw_dropoff = request.GET.get("to", "")
    dropoff = _parse_int(raw_dropoff, 1, MAX_ZONE_ID) if raw_dropoff != "" else None
    day = _parse_int(request.GET.get("day", now.weekday()), 0, 6)
    hour = _parse_int(request.GET.get("hour", now.hour), 0, 23)
    if (
        pickup is None
        or (raw_dropoff != "" and dropoff is None)
        or day is None
        or hour is None
        or unknown_zone_ids(pickup, dropoff)
    ):
        return None
    return pickup, dropoff, day, hour


def _route_response(request, stats_function):
    """Validate a /api/routes-style request and answer it with
    stats_function(pickup, dropoff, day, hour), or 400 if it is invalid."""
    query = _route_query(request)
    if query is None:
        return JsonResponse({"error": ROUTE_QUERY_ERROR}, status=400)
    pickup, dropoff, day, hour = query
    return JsonResponse(
        {
            "from": pickup,
            "to": dropoff,
            "day": day,
            "hour": hour,
            **stats_function(pickup, dropoff, day, hour),
        }
    )


@require_GET
def routes_api(request):
    """GET /api/routes?from=&to=&day=&hour=

    Fare before tip (min/avg/max), average duration and trip count for one
    day of week (Monday=0 .. Sunday=6) and hour (0-23), defaulting to the
    current NYC day and hour. With `to`, for that route; without it, for
    all trips from the pickup zone. Below settings.MIN_TRIP_COUNT trips,
    enough_data is false and the stats are null.
    """
    return _route_response(request, route_stats)


@require_GET
def rideshare_routes_api(request):
    """GET /api/routes/rideshare?from=&to=&day=&hour=

    The Uber and Lyft (combined) twin of /api/routes (US28 #75): the same
    parameters, validation, defaults and enough_data rule, read from the
    rideshare tables, with the typical wait for pickup (avg_wait_min) as
    an extra key. avg_wait_min is null when fewer than
    settings.MIN_TRIP_COUNT trips have a valid wait.
    """
    return _route_response(request, rideshare_route_stats)


@require_GET
def route_windows_api(request):
    """GET /api/routes/windows?from=&to=&day=

    The hours of one day of week (Monday=0 .. Sunday=6, default the current
    NYC day) ranked by average fare and by average duration, with the best
    (cheapest, fastest) and worst (most expensive, slowest) hour. With `to`,
    for that route; without it, for all trips from the pickup zone. Hours
    below settings.MIN_TRIP_COUNT trips are left out; fewer than 2 hours
    left gives enough_data false and empty results.
    """
    pickup = _parse_int(request.GET.get("from"), 1, MAX_ZONE_ID)
    raw_dropoff = request.GET.get("to", "")
    dropoff = _parse_int(raw_dropoff, 1, MAX_ZONE_ID) if raw_dropoff != "" else None
    day = _parse_int(request.GET.get("day", datetime.now(NYC_TZ).weekday()), 0, 6)
    if (
        pickup is None
        or (raw_dropoff != "" and dropoff is None)
        or day is None
        or unknown_zone_ids(pickup, dropoff)
    ):
        return JsonResponse(
            {
                "error": "from must be a known zone id; to, if given, must be a "
                "known zone id; day must be 0-6 (Monday=0)"
            },
            status=400,
        )

    return JsonResponse(
        {
            "from": pickup,
            "to": dropoff,
            "day": day,
            **route_windows(pickup, dropoff, day),
        }
    )
