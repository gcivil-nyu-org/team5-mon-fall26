"""US47 #121: restrict an account. A restricted user can still sign in,
browse and use their saved routes and plans, but cannot post a ride, show
interest, send a message or report a fare. Restrictions and lifts are rows
in US46's AccountAction history; the latest restrict or lift row of an
account decides whether it is restricted. A restriction with an end date
stops applying at the start of the day after it (New York time); that is
checked when the user acts, so no scheduled job is needed, and the
automatic lift is recorded like any other."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import AccountAction

NYC_TZ = ZoneInfo("America/New_York")
AUTO_LIFT_BY = "automatic"
BLOCKED_FEATURES = "post rides, show interest, send messages or report fares"


def ends_at_for(end_date):
    """The moment a restriction with this last day stops applying."""
    if end_date is None:
        return None
    return datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=NYC_TZ)


def last_day(restriction):
    """The last restricted day (New York time), or None without an end date."""
    if restriction.ends_at is None:
        return None
    return (timezone.localtime(restriction.ends_at, NYC_TZ) - timedelta(days=1)).date()


def _latest(user_id):
    return (
        AccountAction.objects.filter(
            user_id=user_id, action__in=[AccountAction.RESTRICT, AccountAction.LIFT]
        )
        .order_by("-acted_at", "-pk")
        .first()
    )


def active_restriction(user, now=None):
    """The restriction that applies to `user` now, or None. A restriction
    whose end date has passed is lifted here, and the lift recorded."""
    if user is None or not user.is_authenticated:
        return None
    now = now or timezone.now()
    latest = _latest(user.pk)
    if latest is None or latest.action != AccountAction.RESTRICT:
        return None
    if latest.ends_at is None or latest.ends_at > now:
        return latest
    _lift_expired(user.pk, latest)
    return None


def _lift_expired(user_id, restriction):
    with transaction.atomic():
        # Lock the account so two requests at once record one lift.
        get_user_model().objects.select_for_update().get(pk=user_id)
        if _latest(user_id) != restriction:
            return
        AccountAction.objects.create(
            user_id=user_id,
            action=AccountAction.LIFT,
            reason=f"End date {last_day(restriction):%Y-%m-%d} passed",
            acted_by=AUTO_LIFT_BY,
        )


def notice(restriction):
    """What a restricted user sees wherever a blocked feature is."""
    end = last_day(restriction)
    until = f" until the end of {end:%a} {end.day} {end:%b %Y}" if end else ""
    return (
        f"Your account is restricted{until}, so you can't {BLOCKED_FEATURES}. "
        f"Reason: {restriction.reason} "
        "You can still browse and use your saved routes and plans."
    )


def blocked_notice(user, now=None):
    """The notice if `user` is restricted now, otherwise None."""
    restriction = active_restriction(user, now)
    return notice(restriction) if restriction else None


def restrict(user_id, actor, reason, end_date=None, now=None):
    """Return (changed, explanation). Restricting an account that is already
    restricted replaces its reason and end date."""
    reason = reason.strip()
    if not reason:
        return False, "Enter a reason before restricting an account."
    now = now or timezone.now()
    if end_date is not None and end_date < timezone.localtime(now, NYC_TZ).date():
        return False, "The end date can't be in the past."
    if user_id == actor.pk:
        return False, "You cannot restrict your own account."
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user_id)
        AccountAction.objects.create(
            user=user,
            action=AccountAction.RESTRICT,
            reason=reason,
            acted_by=actor.get_username(),
            ends_at=ends_at_for(end_date),
        )
    return True, "Account restricted."


def lift(user_id, actor, reason, now=None):
    """Return (changed, explanation)."""
    reason = reason.strip()
    if not reason:
        return False, "Enter a reason before lifting a restriction."
    user = get_user_model().objects.get(pk=user_id)
    if active_restriction(user, now) is None:
        return False, f"{user.get_username()} is not restricted."
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user_id)
        if (_latest(user.pk) or AccountAction()).action != AccountAction.RESTRICT:
            return False, f"{user.get_username()} is not restricted."
        AccountAction.objects.create(
            user=user,
            action=AccountAction.LIFT,
            reason=reason,
            acted_by=actor.get_username(),
        )
    return True, "Restriction lifted."


class RestrictionContext:
    """For templates: computed only if a page asks, once per request."""

    def __init__(self, user):
        self.user = user
        self._done = False
        self._notice = None

    @property
    def notice(self):
        if not self._done:
            self._notice = blocked_notice(self.user)
            self._done = True
        return self._notice


def restriction_context(request):
    """Context processor: `account_restriction.notice` on every page."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"account_restriction": RestrictionContext(user)}
