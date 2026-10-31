import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from zones.stats import unknown_zone_ids
from zones.views import MAX_ZONE_ID, _parse_int, map_view

from .forms import NAME_TAKEN, RouteNameForm, SavedRouteForm
from .models import SavedRoute
from .planning import cheapest_in_window, leave_by


@require_GET
def leave_by_api(request):
    """GET /api/routes/leave-by?from=&to=&day=&arrive=HH:MM."""
    pickup = _parse_int(request.GET.get("from"), 1, MAX_ZONE_ID)
    dropoff = _parse_int(request.GET.get("to"), 1, MAX_ZONE_ID)
    day = _parse_int(request.GET.get("day"), 0, 6)
    arrive = request.GET.get("arrive", "")
    match = re.fullmatch(r"([01]\d|2[0-3]):(00|15|30|45)", arrive)
    if (
        pickup is None
        or dropoff is None
        or day is None
        or match is None
        or unknown_zone_ids(pickup, dropoff)
    ):
        return JsonResponse(
            {
                "error": "from and to must be known zone ids; day must be 0-6 "
                "(Monday=0); arrive must be HH:MM in 15-minute steps"
            },
            status=400,
        )

    return JsonResponse(
        {
            "from": pickup,
            "to": dropoff,
            "day": day,
            "arrive": arrive,
            **leave_by(pickup, dropoff, day, int(match[1]), int(match[2])),
        }
    )


@require_GET
def cheapest_api(request):
    """GET /api/routes/cheapest?from=&to=&day=&start=HH:MM (US16 #45).

    Same zone and day validation as /api/routes/leave-by. `start` is any
    HH:MM, so "Now" can send the exact current NYC time; the map's custom
    start time picker moves in 15-minute steps.
    """
    pickup = _parse_int(request.GET.get("from"), 1, MAX_ZONE_ID)
    dropoff = _parse_int(request.GET.get("to"), 1, MAX_ZONE_ID)
    day = _parse_int(request.GET.get("day"), 0, 6)
    start = request.GET.get("start", "")
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", start)
    if (
        pickup is None
        or dropoff is None
        or day is None
        or match is None
        or unknown_zone_ids(pickup, dropoff)
    ):
        return JsonResponse(
            {
                "error": "from and to must be known zone ids; day must be 0-6 "
                "(Monday=0); start must be HH:MM"
            },
            status=400,
        )

    return JsonResponse(
        {
            "from": pickup,
            "to": dropoff,
            "day": day,
            "start": start,
            **cheapest_in_window(pickup, dropoff, day, int(match[1]), int(match[2])),
        }
    )


@require_POST
def save_route(request):
    """Save only for the current account; never accept an owner from the client."""
    if not request.user.is_authenticated:
        return JsonResponse({"message": "Sign in to save routes"}, status=401)
    form = SavedRouteForm(request.user, request.POST)
    if form.is_valid():
        route = form.save()
        if route is not None:
            return JsonResponse({"id": route.pk, "name": route.name}, status=201)
    return JsonResponse({"errors": form.errors}, status=400)


@login_required
@require_GET
def my_routes(request):
    routes = SavedRoute.objects.filter(user=request.user).select_related(
        "pickup_zone", "dropoff_zone"
    )
    return render(request, "routes/my_routes.html", {"routes": routes})


@login_required
@require_GET
def open_saved_route(request, route_id):
    route = get_object_or_404(SavedRoute, pk=route_id, user=request.user)
    return map_view(request, saved_route=route)


@login_required
@require_http_methods(["GET", "POST"])
def rename_saved_route(request, route_id):
    route = get_object_or_404(SavedRoute, pk=route_id, user=request.user)
    form = RouteNameForm(
        request.user,
        request.POST if request.method == "POST" else None,
        route=route,
        initial={"name": route.name},
    )
    if request.method == "POST" and form.is_valid():
        route.name = form.cleaned_data["name"]
        try:
            with transaction.atomic():
                route.save(update_fields=["name"])
        except IntegrityError:
            if (
                not SavedRoute.objects.filter(user=request.user, name=route.name)
                .exclude(pk=route.pk)
                .exists()
            ):
                raise
            form.add_error("name", NAME_TAKEN)
        else:
            messages.success(request, "Route renamed.")
            return redirect("routes:my_routes")
    return render(request, "routes/rename_route.html", {"route": route, "form": form})


@login_required
@require_http_methods(["GET", "POST"])
def delete_saved_route(request, route_id):
    route = get_object_or_404(SavedRoute, pk=route_id, user=request.user)
    if request.method == "POST":
        route.delete()
        messages.success(request, "Route deleted.")
        return redirect("routes:my_routes")
    return render(request, "routes/delete_route.html", {"route": route})
