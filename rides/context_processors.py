"""US37 #99: the "My rides" badge in the nav, on every page."""

from .my_rides import Badge


def ride_badge(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"ride_badge": Badge(user)}
