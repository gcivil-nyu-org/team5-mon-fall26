from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_http_methods

from accounts.display_name import display_name_of, display_name_required
from zones.views import MAX_ZONE_ID, NYC_TZ, _parse_int

from .forms import RidePostForm, RideSearchForm, requested_departure
from .models import RidePost
from .search import date_for_day, find_rides

POSTED = (
    "Your shared ride is posted. Riders going your way will see your display "
    "name, never your email address."
)


@display_name_required
@require_http_methods(["GET", "POST"])
def post_ride(request):
    """US31 #93: "Post a shared ride". ?from=&to= fill in the zones from the
    trip summary; ?date=&time= fill in the departure from an empty search
    (US32 #94). Guests see a sign-in prompt in place of the form; a rider
    without a display name chooses one first (US30 #92)."""
    if not request.user.is_authenticated:
        next_page = urlencode({"next": request.get_full_path()})
        signin = f"{reverse('accounts:signin')}?{next_page}"
        return render(request, "rides/post_ride.html", {"signin_url": signin})

    if request.method == "POST":
        form = RidePostForm(request.user, request.POST)
        if form.is_valid() and (post := form.save()) is not None:
            messages.success(request, POSTED)
            return redirect("rides:ride_detail", post_id=post.pk)
    else:
        form = RidePostForm(
            request.user,
            initial={
                "pickup_zone": _parse_int(request.GET.get("from"), 1, MAX_ZONE_ID),
                "dropoff_zone": _parse_int(request.GET.get("to"), 1, MAX_ZONE_ID),
                "departure_at": requested_departure(
                    request.GET.get("date"), request.GET.get("time"), timezone.now()
                ),
            },
        )
    return render(request, "rides/post_ride.html", {"form": form})


@login_required
@require_GET
def ride_detail(request, post_id):
    """The post as other riders will see it. Only its owner can open it
    until ride search (US32) and interest (US33) open it to other riders."""
    post = get_object_or_404(
        RidePost.objects.select_related(
            "owner__profile", "pickup_zone", "dropoff_zone"
        ),
        pk=post_id,
        owner=request.user,
    )
    return render(
        request,
        "rides/ride_detail.html",
        {
            "post": post,
            "owner_name": display_name_of(post.owner),
            "status": post.status_label(),
        },
    )


def _signin_prompt(request, template):
    next_page = urlencode({"next": request.get_full_path()})
    signin = f"{reverse('accounts:signin')}?{next_page}"
    return render(request, template, {"signin_url": signin})


@display_name_required
@require_GET
def find_rides_view(request):
    """US32 #94: "Find a shared ride". ?from=&to=&date= search at once, and
    &time= keeps posts within 1 hour of it. From the trip summary, ?day=
    (Monday=0) becomes the next date on that weekday. Guests see a sign-in
    prompt in place of the list."""
    if not request.user.is_authenticated:
        return _signin_prompt(request, "rides/find_rides.html")

    now = timezone.now()
    params = request.GET.copy()
    if not params.get("date") and (day := date_for_day(params.get("day"), now)):
        params["date"] = day.isoformat()
    context = {}
    if params.get("from") and params.get("to") and params.get("date"):
        form = RideSearchForm(params, now=now)
        if form.is_valid():
            data = form.cleaned_data
            context["matches"] = find_rides(
                request.user, data["from"], data["to"], data["date"], data["time"], now
            )
            link = {
                "from": data["from"].pk,
                "to": data["to"].pk,
                "date": data["date"].isoformat(),
            }
            if data["time"] is not None:
                link["time"] = f"{data['time']:%H:%M}"
            context["post_link"] = f"{reverse('rides:post_ride')}?{urlencode(link)}"
    else:
        form = RideSearchForm(
            now=now,
            initial={
                "from": _parse_int(params.get("from"), 1, MAX_ZONE_ID),
                "to": _parse_int(params.get("to"), 1, MAX_ZONE_ID),
                "date": now.astimezone(NYC_TZ).date(),
            },
        )
    context["form"] = form
    return render(request, "rides/find_rides.html", context)
