from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_http_methods

from zones.stats import unknown_zone_ids
from zones.views import MAX_ZONE_ID, NYC_TZ, _parse_int

from .forms import FareReportForm
from .models import FareReport

SAVED = "Thanks! Your fare report was saved."
UPDATED = "Fare report updated."
DELETED = "Fare report deleted."
HELD = (
    " It is far from the usual fare for this trip, so it will be checked "
    "before other riders see it."
)


def _money_median(amounts):
    return str(median(amounts).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@require_GET
def route_reports(request):
    """US26 #73: public rider fares for one route, from the last 90 days."""
    pickup = _parse_int(request.GET.get("from"), 1, MAX_ZONE_ID)
    dropoff = _parse_int(request.GET.get("to"), 1, MAX_ZONE_ID)
    if pickup is None or dropoff is None or unknown_zone_ids(pickup, dropoff):
        return JsonResponse({"error": "from and to must be known zone ids"}, status=400)

    now = timezone.now()
    reports = list(
        FareReport.objects.public()
        .filter(
            pickup_zone_id=pickup,
            dropoff_zone_id=dropoff,
            ride_at__gte=now - timedelta(days=90),
            ride_at__lte=now,
        )
        .order_by("-ride_at", "-pk")
        .values("ride_at", "taxi_fare", "rideshare_service", "rideshare_quote")
    )
    count = len(reports)
    result = {
        "from": pickup,
        "to": dropoff,
        "enough_data": count >= 3,
        "report_count": count,
        "median_taxi_fare": None,
        "rideshare_quote_count": 0,
        "median_rideshare_quote": None,
        "recent_reports": [],
    }
    if count < 3:
        return JsonResponse(result)

    quotes = [
        row["rideshare_quote"] for row in reports if row["rideshare_quote"] is not None
    ]
    result["median_taxi_fare"] = _money_median([row["taxi_fare"] for row in reports])
    result["rideshare_quote_count"] = len(quotes)
    if quotes:
        result["median_rideshare_quote"] = _money_median(quotes)
    result["recent_reports"] = [
        {
            "ride_day": timezone.localtime(row["ride_at"], NYC_TZ).date().isoformat(),
            "ride_hour": timezone.localtime(row["ride_at"], NYC_TZ).hour,
            "taxi_fare": str(row["taxi_fare"]),
            "rideshare_service": row["rideshare_service"] or None,
            "rideshare_quote": (
                str(row["rideshare_quote"])
                if row["rideshare_quote"] is not None
                else None
            ),
        }
        for row in reports[:5]
    ]
    return JsonResponse(result)


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
