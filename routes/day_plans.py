"""US20 #49: rules for multi-stop day plans, kept out of the views."""

from django.db import transaction

from .models import DayPlan, DayPlanStop

# Stop-count messages, shared by the map's save form and the plan page.
TOO_FEW_STOPS = (
    f"A day plan needs at least {DayPlan.MIN_STOPS} stops "
    f"({DayPlan.MIN_STOPS - 1} trips)."
)
TOO_FEW_TO_REMOVE = f"{TOO_FEW_STOPS} Add a stop before removing one."
TOO_MANY_STOPS = f"A day plan can have at most {DayPlan.MAX_STOPS} stops."


def create_day_plan(user, name, day, zones, leave_times):
    """Save a plan and its stops in order. zones are the stops' Zone objects;
    leave_times has one time per stop except the last."""
    with transaction.atomic():
        plan = DayPlan.objects.create(user=user, name=name, day_of_week=day)
        DayPlanStop.objects.bulk_create(
            DayPlanStop(
                day_plan=plan,
                zone=zone,
                position=position,
                leave_time=leave_times[position] if position < len(zones) - 1 else None,
            )
            for position, zone in enumerate(zones)
        )
    return plan


def out_of_order_warning(stops):
    """A warning when a leave time is not after the one before it, else None.

    Leave times out of order are allowed (the rider may mean it); the page
    only points them out.
    """
    timed = [stop for stop in stops if stop.leave_time is not None]
    for earlier, later in zip(timed, timed[1:]):
        if later.leave_time <= earlier.leave_time:
            relation = (
                "is before"
                if later.leave_time < earlier.leave_time
                else "is the same as"
            )
            return (
                "Leave times are not in order: "
                f"{later.zone.name} ({later.leave_label}) {relation} "
                f"{earlier.zone.name} ({earlier.leave_label})."
            )
    return None


# ---- Pass B: editing a saved plan ----
#
# Every change runs in one transaction with the plan row locked
# (select_for_update), so two tabs cannot interleave edits. Reordering moves
# the places, not the times: zones are reassigned by position and each
# position keeps its leave time. Removing a stop deletes its row (and its
# time) and moves the later rows up one, row by row in ascending order,
# because PostgreSQL checks the unique (day_plan, position) row by row.

STOPS_CHANGED = "The stops have changed. Reload the page and try again."
ALREADY_FIRST = "This stop is already the first."
ALREADY_LAST = "This stop is already the last."
LAST_STOP_TIME = "The last stop has no leave time."


class DayPlanError(Exception):
    """A change the rules block, with a message for the rider."""


def _locked_stops(plan):
    """Lock the plan row and return its stops in order (inside atomic())."""
    DayPlan.objects.select_for_update().get(pk=plan.pk)
    return list(DayPlanStop.objects.filter(day_plan=plan).order_by("position"))


def _index(stops, stop_id):
    for i, stop in enumerate(stops):
        if stop.pk == stop_id:
            return i
    raise DayPlanError(STOPS_CHANGED)


def move_stop(plan, stop_id, direction):
    """Swap a stop's place with the one before ("up") or after ("down").
    The leave times stay with their positions."""
    with transaction.atomic():
        stops = _locked_stops(plan)
        i = _index(stops, stop_id)
        j = i - 1 if direction == "up" else i + 1
        if j < 0:
            raise DayPlanError(ALREADY_FIRST)
        if j >= len(stops):
            raise DayPlanError(ALREADY_LAST)
        stops[i].zone_id, stops[j].zone_id = stops[j].zone_id, stops[i].zone_id
        for stop in (stops[i], stops[j]):
            stop.save(update_fields=["zone"])


def reorder_stops(plan, stop_ids):
    """Put the places in the order of stop_ids (every stop id of the plan,
    once). The leave times stay with their positions."""
    with transaction.atomic():
        stops = _locked_stops(plan)
        by_id = {stop.pk: stop for stop in stops}
        if len(stop_ids) != len(stops) or set(stop_ids) != set(by_id):
            raise DayPlanError(STOPS_CHANGED)
        zones = [by_id[stop_id].zone_id for stop_id in stop_ids]
        for stop, zone_id in zip(stops, zones):
            if stop.zone_id != zone_id:
                stop.zone_id = zone_id
                stop.save(update_fields=["zone"])


def remove_stop(plan, stop_id):
    """Remove a stop: its two legs merge, the stop before keeps its leave
    time and the removed stop's time goes. A new last stop has no time."""
    with transaction.atomic():
        stops = _locked_stops(plan)
        i = _index(stops, stop_id)
        if len(stops) <= DayPlan.MIN_STOPS:
            raise DayPlanError(TOO_FEW_TO_REMOVE)
        stops.pop(i).delete()
        for stop in stops[i:]:
            stop.position -= 1
            stop.save(update_fields=["position"])
        if i == len(stops):  # the last stop was removed
            stops[-1].leave_time = None
            stops[-1].save(update_fields=["leave_time"])


def add_stop(plan, zone, previous_leave_time):
    """Add a stop at the end; the old last stop leaves at previous_leave_time."""
    with transaction.atomic():
        stops = _locked_stops(plan)
        if len(stops) >= DayPlan.MAX_STOPS:
            raise DayPlanError(TOO_MANY_STOPS)
        stops[-1].leave_time = previous_leave_time
        stops[-1].save(update_fields=["leave_time"])
        DayPlanStop.objects.create(day_plan=plan, zone=zone, position=len(stops))


def set_leave_time(plan, stop_id, leave_time):
    """Change when the rider leaves a stop (every stop except the last)."""
    with transaction.atomic():
        stops = _locked_stops(plan)
        i = _index(stops, stop_id)
        if i == len(stops) - 1:
            raise DayPlanError(LAST_STOP_TIME)
        stops[i].leave_time = leave_time
        stops[i].save(update_fields=["leave_time"])
