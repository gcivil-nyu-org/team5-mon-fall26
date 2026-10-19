import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Zone, ZoneHourStats

ZONE_SHAPES_PATH = Path(__file__).resolve().parent / "data" / "taxi_zones.geojson"

# Trip times are recorded in NYC local time, so "now" must be NYC time too.
NYC_TZ = ZoneInfo("America/New_York")


def map_view(request):
    """The main page: a Leaflet map of NYC taxi zones colored by demand."""
    now = datetime.now(NYC_TZ)
    return render(
        request,
        "zones/map.html",
        {"current_day": now.weekday(), "current_hour": now.hour},
    )


@lru_cache(maxsize=1)
def load_zone_shapes():
    """Read the zone GeoJSON once and keep it in memory."""
    with ZONE_SHAPES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


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
                    "avg_duration_min": zone_stats["avg_duration_min"] if zone_stats else None,
                    "fare_min": zone_stats["fare_min"] if zone_stats else None,
                    "fare_avg": zone_stats["fare_avg"] if zone_stats else None,
                    "fare_max": zone_stats["fare_max"] if zone_stats else None,
                },
            }
        )

    return JsonResponse(
        {"type": "FeatureCollection", "day": day, "hour": hour, "features": features}
    )
