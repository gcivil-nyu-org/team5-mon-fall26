import re
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from zones.stats import unknown_zone_ids
from zones.views import MAX_ZONE_ID, NYC_TZ, _parse_int, map_view

from .forms import NAME_TAKEN, PlanTimeForm, RouteNameForm, SavedRouteForm, TripPlanForm
from .models import SavedRoute, TripPlan
from .calendar import build_ics
from .planning import cheaper_nearby, cheapest_in_window, leave_by, plan_calendar


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


@require_GET
def nearby_api(request):
    """GET /api/routes/nearby?from=&to=&day=&hour= (US19 #48).

    Adjacent pickup zones where the same trip is historically cheaper.
    `to` is required; day and hour default to the current NYC day and
    hour, as in /api/routes.
    """
    now = datetime.now(NYC_TZ)
    pickup = _parse_int(request.GET.get("from"), 1, MAX_ZONE_ID)
    dropoff = _parse_int(request.GET.get("to"), 1, MAX_ZONE_ID)
    day = _parse_int(request.GET.get("day", now.weekday()), 0, 6)
    hour = _parse_int(request.GET.get("hour", now.hour), 0, 23)
    if (
        pickup is None
        or dropoff is None
        or day is None
        or hour is None
        or unknown_zone_ids(pickup, dropoff)
    ):
        return JsonResponse(
            {
                "error": "from and to must be known zone ids; day must be 0-6 "
                "(Monday=0) and hour must be 0-23"
            },
            status=400,
        )

    return JsonResponse(
        {
            "from": pickup,
            "to": dropoff,
            "day": day,
            "hour": hour,
            **cheaper_nearby(pickup, dropoff, day, hour),
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


# ---- US17 #46: saved "Leave by" plans ----


@require_POST
def save_plan(request):
    """Save a plan for the current account; the owner never comes from the client."""
    if not request.user.is_authenticated:
        return JsonResponse({"message": "Sign in to save plans"}, status=401)
    form = TripPlanForm(request.user, request.POST)
    if form.is_valid():
        plan = form.save()
        if plan is not None:
            return JsonResponse({"id": plan.pk, "name": plan.name}, status=201)
    return JsonResponse({"errors": form.errors}, status=400)


def _own_plan(request, plan_id):
    return get_object_or_404(
        TripPlan.objects.select_related("pickup_zone", "dropoff_zone"),
        pk=plan_id,
        user=request.user,
    )


@login_required
@require_GET
def my_plans(request):
    plans = TripPlan.objects.filter(user=request.user).select_related(
        "pickup_zone", "dropoff_zone"
    )
    return render(request, "routes/my_plans.html", {"plans": plans})


@login_required
@require_GET
def open_plan(request, plan_id):
    """Show the plan with its result recalculated now (nothing stale is stored)."""
    plan = _own_plan(request, plan_id)
    calendar = plan_calendar(plan, datetime.now(NYC_TZ))
    return render(
        request,
        "routes/plan_detail.html",
        {"plan": plan, "result": calendar["result"], "calendar": calendar},
    )


@login_required
@require_GET
def plan_calendar_ics(request, plan_id):
    """GET /plans/<id>/calendar.ics (US21 #50): the plan as a calendar event.

    The same plan_calendar() as the plan page's button, so they agree. The
    file names nobody: no email, username or user id, and the filename only
    has the plan id.
    """
    plan = _own_plan(request, plan_id)
    now = datetime.now(NYC_TZ)
    weekly = request.GET.get("repeat") == "weekly"
    event = plan_calendar(plan, now, weekly=weekly)["event"]
    response = HttpResponse(
        build_ics([event], now), content_type="text/calendar; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="plan-{plan.pk}.ics"'
    return response


@login_required
@require_http_methods(["GET", "POST"])
def edit_plan(request, plan_id):
    plan = _own_plan(request, plan_id)
    form = PlanTimeForm(
        request.POST if request.method == "POST" else None,
        mode=plan.mode,
        initial={"day_of_week": plan.day_of_week, "time": plan.time_label},
    )
    if request.method == "POST" and form.is_valid():
        plan.day_of_week = form.cleaned_data["day_of_week"]
        plan.time = form.cleaned_data["time"]
        plan.save(update_fields=["day_of_week", "time"])
        messages.success(request, "Plan updated.")
        return redirect("routes:open_plan", plan_id=plan.pk)
    return render(request, "routes/edit_plan.html", {"plan": plan, "form": form})


@login_required
@require_http_methods(["GET", "POST"])
def delete_plan(request, plan_id):
    plan = _own_plan(request, plan_id)
    if request.method == "POST":
        plan.delete()
        messages.success(request, "Plan deleted.")
        return redirect("routes:my_plans")
    return render(request, "routes/delete_plan.html", {"plan": plan})
