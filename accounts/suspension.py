"""US46 account suspension and restoration with related content updates."""

from django.contrib.auth import get_user_model
from django.db import transaction

from reports.models import FareReport
from rides.models import RidePost

from .models import AccountAction


def change_account(user_id, actor, action, reason):
    """Return (changed, explanation). Lock staff before checking the last one."""
    reason = reason.strip()
    if not reason:
        return False, "Enter a reason before changing an account."
    if action not in (AccountAction.SUSPEND, AccountAction.RESTORE):
        raise ValueError("Unknown account action")

    User = get_user_model()
    with transaction.atomic():
        active_staff = list(
            User.objects.filter(is_active=True, is_staff=True)
            .order_by("pk")
            .select_for_update()
            .values_list("pk", flat=True)
        )
        user = User.objects.select_for_update().get(pk=user_id)
        if action == AccountAction.SUSPEND:
            if user.pk == actor.pk:
                return False, "You cannot suspend your own account."
            if not user.is_active:
                return False, "This account is already suspended."
            if user.is_staff and len(active_staff) <= 1:
                return False, "The last active staff account cannot be suspended."
            user.is_active = False
            user.save(update_fields=["is_active"])
            RidePost.objects.filter(
                owner=user, status__in=[RidePost.OPEN, RidePost.FULL]
            ).update(status=RidePost.CLOSED)
            FareReport.objects.filter(user=user, status=FareReport.VISIBLE).update(
                status=FareReport.HELD
            )
        else:
            if user.is_active:
                return False, "This account is already active."
            user.is_active = True
            user.save(update_fields=["is_active"])

        AccountAction.objects.create(
            user=user, action=action, reason=reason, acted_by=actor.get_username()
        )
    return True, (
        "Account suspended." if action == AccountAction.SUSPEND else "Account restored."
    )
