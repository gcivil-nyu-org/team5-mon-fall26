from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import SignUpForm


@require_http_methods(["GET", "POST"])
def signup(request):
    """US10 #39: create an account with an email and a password, then sign
    in and go back to the map."""
    if request.user.is_authenticated:
        return redirect("zones:map")

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if user is not None:
            login(request, user)
            return redirect("zones:map")
    return render(request, "accounts/signup.html", {"form": form})


@login_required
def account(request):
    """My account. Needs an account, so guests go to sign-in (LOGIN_URL)
    with ?next= and come back here after signing in (US11 #40)."""
    return render(request, "accounts/account.html")
