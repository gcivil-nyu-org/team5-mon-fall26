from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .display_name import display_name_of
from .forms import DeleteAccountForm, DisplayNameForm, SignUpForm

NAME_SAVED = "Your display name was saved."


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

    def get_context_data(self, **kwargs):
        """US30 #92: the display name form sits above the password form and
        posts to its own page, so the two forms never mix."""
        context = super().get_context_data(**kwargs)
        context["display_name"] = display_name_of(self.request.user)
        context["display_name_form"] = DisplayNameForm(self.request.user)
        return context


def _safe_next(request, next_page):
    """next_page if it is on this site, else My account."""
    if next_page and url_has_allowed_host_and_scheme(
        next_page,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_page
    return reverse("accounts:account")


@login_required
@require_http_methods(["GET", "POST"])
def display_name(request):
    """US30 #92: choose or change the display name, then go back to `next`
    (My account, or the ride-sharing page that asked for a name)."""
    next_page = request.POST.get("next", request.GET.get("next", ""))
    form = DisplayNameForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid() and form.save() is not None:
        messages.success(request, NAME_SAVED)
        return redirect(_safe_next(request, next_page))
    return render(
        request,
        "accounts/display_name.html",
        {"form": form, "next": next_page},
    )


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
