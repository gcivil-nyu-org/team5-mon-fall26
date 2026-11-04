from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_http_methods

from zones.views import MAX_ZONE_ID, _parse_int

from .forms import FareReportForm
from .models import FareReport

SAVED = "Thanks! Your fare report was saved."
HELD = (
    " It is far from the usual fare for this trip, so it will be checked "
    "before other riders see it."
)


@require_http_methods(["GET", "POST"])
def report_fare(request):
    """US24 #71: the "Report a fare" form. ?from=&to= fill in the zones
    from the trip summary. Guests see a sign-in prompt in place of the form."""
    pickup = _parse_int(request.GET.get("from"), 1, MAX_ZONE_ID)
    dropoff = _parse_int(request.GET.get("to"), 1, MAX_ZONE_ID)
    if not request.user.is_authenticated:
        next_page = urlencode({"next": request.get_full_path()})
        signin = f"{reverse('accounts:signin')}?{next_page}"
        return render(request, "reports/report_fare.html", {"signin_url": signin})

    if request.method == "POST":
        form = FareReportForm(request.user, request.POST)
        if form.is_valid():
            report = form.save()
            message = SAVED + (HELD if report.status == FareReport.HELD else "")
            messages.success(request, message)
            return redirect(request.get_full_path())
    else:
        now = timezone.now().replace(second=0, microsecond=0)
        form = FareReportForm(
            request.user,
            initial={"pickup_zone": pickup, "dropoff_zone": dropoff, "ride_at": now},
        )
    return render(request, "reports/report_fare.html", {"form": form})
