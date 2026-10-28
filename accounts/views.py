from django.contrib.auth import login
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
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


class AccountView(SuccessMessageMixin, PasswordChangeView):
    """My account (US12 #41) with Django's change-password form. It needs
    an account, so guests go to sign-in with ?next= and come back here
    (US11 #40). After a change the user stays signed in."""

    template_name = "accounts/account.html"
    success_url = reverse_lazy("accounts:account")
    success_message = "Your password was changed."
