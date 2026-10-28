from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_http_methods

from .forms import DeleteAccountForm, SignUpForm


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


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request):
    """US12 #41: delete the account after the user confirms with their
    password, then sign out and go to the map. Everything linked to the
    user is deleted with it (on_delete=CASCADE)."""
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.delete()  # one transaction, with everything linked to it
        logout(request)
        return redirect("zones:map")
    return render(request, "accounts/delete.html", {"form": form})
