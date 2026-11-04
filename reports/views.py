from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_http_methods

from zones.views import MAX_ZONE_ID, _parse_int

from .forms import FareReportForm
from .models import FareReport

SAVED = "Thanks! Your fare report was saved."
UPDATED = "Fare report updated."
DELETED = "Fare report deleted."
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


# ---- US25 #72: my fare reports ----


@login_required
@require_GET
def my_reports(request):
    """All of the rider's own reports, held ones included, newest first."""
    reports = FareReport.objects.filter(user=request.user).select_related(
        "pickup_zone", "dropoff_zone"
    )
    return render(request, "reports/my_reports.html", {"reports": reports})


def _own_report(request, report_id):
    """The rider's own report; another user's, or a missing one, is 404."""
    return get_object_or_404(
        FareReport.objects.select_related("pickup_zone", "dropoff_zone"),
        pk=report_id,
        user=request.user,
    )


@login_required
@require_http_methods(["GET", "POST"])
def edit_report(request, report_id):
    """The US24 form and rules, then the review check again."""
    report = _own_report(request, report_id)
    form = FareReportForm(
        request.user,
        request.POST if request.method == "POST" else None,
        instance=report,
    )
    if request.method == "POST" and form.is_valid():
        report = form.save()
        message = UPDATED + (HELD if report.status == FareReport.HELD else "")
        messages.success(request, message)
        return redirect("reports:my_reports")
    return render(request, "reports/edit_report.html", {"report": report, "form": form})


@login_required
@require_http_methods(["GET", "POST"])
def delete_report(request, report_id):
    report = _own_report(request, report_id)
    if request.method == "POST":
        report.delete()
        messages.success(request, DELETED)
        return redirect("reports:my_reports")
    return render(request, "reports/delete_report.html", {"report": report})
