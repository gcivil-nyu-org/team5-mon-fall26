from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_http_methods

from accounts.display_name import display_name_of, display_name_required
from zones.views import MAX_ZONE_ID, _parse_int

from .forms import RidePostForm, default_departure
from .models import RidePost

POSTED = (
    "Your shared ride is posted. Riders going your way will see your display "
    "name, never your email address."
)


@display_name_required
@require_http_methods(["GET", "POST"])
def post_ride(request):
    """US31 #93: "Post a shared ride". ?from=&to= fill in the zones from the
    trip summary. Guests see a sign-in prompt in place of the form; a rider
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
                "departure_at": default_departure(timezone.now()),
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
