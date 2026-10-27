from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import SignUpForm


@require_http_methods(["GET", "POST"])
def signup(request):
    """US10 #39: create an account with an email and a password."""
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and form.save():
        return redirect("zones:map")
    return render(request, "accounts/signup.html", {"form": form})
