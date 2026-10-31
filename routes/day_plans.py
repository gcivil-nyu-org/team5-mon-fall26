"""US20 #49: rules for multi-stop day plans, kept out of the views."""

from django.db import transaction

from .models import DayPlan, DayPlanStop


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
