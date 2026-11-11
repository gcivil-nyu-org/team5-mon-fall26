"""US30 #92: ride-sharing features need a display name first."""

from functools import wraps

from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode


def display_name_of(user):
    """The name other riders see, or None. Never falls back to the email."""
    if not user.is_authenticated:
        return None
    try:
        return user.profile.display_name
    except ObjectDoesNotExist:
        return None


def display_name_required(view):
    """Send a signed-in rider without a display name to choose one, then
    back to the same page (posting a ride, showing interest, messaging).

    Guests reach the view unchanged: it shows them a sign-in prompt, or is
    also decorated with @login_required (put that one first)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated and display_name_of(request.user) is None:
            next_page = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('accounts:display_name')}?{next_page}")
        return view(request, *args, **kwargs)

    return wrapper
