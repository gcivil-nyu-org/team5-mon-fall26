import re
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from zones.stats import unknown_zone_ids
from zones.views import MAX_ZONE_ID, NYC_TZ, _parse_int, map_view

from .forms import (
    NAME_TAKEN,
    AddStopForm,
    DayPlanDayForm,
    DayPlanForm,
    MoveStopForm,
    PlanTimeForm,
    RouteNameForm,
    SavedRouteForm,
    StopTimeForm,
    TripPlanForm,
)
from .models import DayPlan, DayPlanStop, SavedRoute, TripPlan
from .calendar import build_ics
from .day_plans import (
    TOO_MANY_STOPS,
    DayPlanError,
    add_stop,
    move_stop,
    out_of_order_warning,
    remove_stop,
    reorder_stops,
    set_leave_time,
)
from .planning import (
    cheaper_nearby,
    cheapest_in_window,
    day_plan_legs,
    leave_by,
    plan_calendar,
)


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


# ---- US20 #49: multi-stop day plans ----


@require_POST
def save_day_plan(request):
    """Save a day plan built on the map; the owner never comes from the client."""
    if not request.user.is_authenticated:
        return JsonResponse({"message": "Sign in to save day plans"}, status=401)
    form = DayPlanForm(request.user, request.POST)
    if form.is_valid():
        plan = form.save()
        if plan is not None:
            return JsonResponse(
                {
                    "id": plan.pk,
                    "name": plan.name,
                    "url": reverse("routes:open_day_plan", args=[plan.pk]),
                },
                status=201,
            )
    return JsonResponse({"errors": form.errors}, status=400)


def _own_day_plan(request, plan_id):
    return get_object_or_404(DayPlan, pk=plan_id, user=request.user)


@login_required
@require_GET
def my_day_plans(request):
    plans = DayPlan.objects.filter(user=request.user).prefetch_related(
        Prefetch("stops", queryset=DayPlanStop.objects.select_related("zone"))
    )
    return render(request, "routes/my_day_plans.html", {"plans": plans})


def _render_day_plan(request, plan, status=200, error=None, add_form=None):
    """The day plan page: stops, legs with statistics, and the edit forms.
    A blocked or invalid change shows its message with status 400."""
    stops = list(plan.stops.select_related("zone"))
    return render(
        request,
        "routes/day_plan_detail.html",
        {
            "plan": plan,
            "stops": stops,
            "legs": day_plan_legs(plan, stops),
            "warning": out_of_order_warning(stops),
            "error": error,
            "can_add": len(stops) < DayPlan.MAX_STOPS,
            "too_many_stops": TOO_MANY_STOPS,
            "add_form": add_form or AddStopForm(),
            "days": DayPlan._meta.get_field("day_of_week").choices,
        },
        status=status,
    )


def _form_error(form):
    return " ".join(message for errors in form.errors.values() for message in errors)


@login_required
@require_GET
def open_day_plan(request, plan_id):
    """The plan's legs with their statistics, recalculated now."""
    return _render_day_plan(request, _own_day_plan(request, plan_id))


def _own_stop(plan, stop_id):
    return get_object_or_404(DayPlanStop, pk=stop_id, day_plan=plan)


def _after_change(request, plan, message):
    messages.success(request, message)
    return redirect("routes:open_day_plan", plan_id=plan.pk)


@login_required
@require_POST
def change_day_plan_day(request, plan_id):
    plan = _own_day_plan(request, plan_id)
    form = DayPlanDayForm(request.POST)
    if not form.is_valid():
        return _render_day_plan(request, plan, 400, _form_error(form))
    plan.day_of_week = form.cleaned_data["day_of_week"]
    plan.save(update_fields=["day_of_week"])
    return _after_change(request, plan, "Day changed.")


@login_required
@require_POST
def set_day_plan_stop_time(request, plan_id, stop_id):
    plan = _own_day_plan(request, plan_id)
    stop = _own_stop(plan, stop_id)
    form = StopTimeForm(request.POST)
    if not form.is_valid():
        return _render_day_plan(request, plan, 400, _form_error(form))
    try:
        set_leave_time(plan, stop.pk, form.cleaned_data["leave_time"])
    except DayPlanError as error:
        return _render_day_plan(request, plan, 400, str(error))
    return _after_change(request, plan, "Leave time changed.")


@login_required
@require_POST
def add_day_plan_stop(request, plan_id):
    plan = _own_day_plan(request, plan_id)
    form = AddStopForm(request.POST)
    if not form.is_valid():
        return _render_day_plan(request, plan, 400, _form_error(form), add_form=form)
    try:
        add_stop(plan, form.cleaned_data["zone"], form.cleaned_data["leave_time"])
    except DayPlanError as error:
        return _render_day_plan(request, plan, 400, str(error), add_form=form)
    return _after_change(request, plan, "Stop added.")


@login_required
@require_POST
def move_day_plan_stop(request, plan_id, stop_id):
    """The up/down buttons; they work without JavaScript."""
    plan = _own_day_plan(request, plan_id)
    stop = _own_stop(plan, stop_id)
    form = MoveStopForm(request.POST)
    if not form.is_valid():
        return _render_day_plan(request, plan, 400, _form_error(form))
    try:
        move_stop(plan, stop.pk, form.cleaned_data["direction"])
    except DayPlanError as error:
        return _render_day_plan(request, plan, 400, str(error))
    return _after_change(request, plan, "Stops reordered.")


@login_required
@require_POST
def remove_day_plan_stop(request, plan_id, stop_id):
    plan = _own_day_plan(request, plan_id)
    stop = _own_stop(plan, stop_id)
    try:
        remove_stop(plan, stop.pk)
    except DayPlanError as error:
        return _render_day_plan(request, plan, 400, str(error))
    return _after_change(request, plan, "Stop removed.")


@login_required
@require_POST
def reorder_day_plan(request, plan_id):
    """POST order=<stop ids, comma-separated, in the new order> (drag and
    drop). JSON: 200 when saved, 400 when it is not exactly the plan's stops."""
    plan = _own_day_plan(request, plan_id)
    try:
        order = [int(value) for value in request.POST.get("order", "").split(",")]
        reorder_stops(plan, order)
    except (ValueError, DayPlanError):
        return JsonResponse(
            {"error": "The stops have changed. Reload the page and try again."},
            status=400,
        )
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["GET", "POST"])
def delete_day_plan(request, plan_id):
    plan = _own_day_plan(request, plan_id)
    if request.method == "POST":
        plan.delete()
        messages.success(request, "Day plan deleted.")
        return redirect("routes:my_day_plans")
    return render(request, "routes/delete_day_plan.html", {"plan": plan})
