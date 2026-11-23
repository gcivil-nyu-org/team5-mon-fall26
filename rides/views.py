from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from accounts.display_name import display_name_of, display_name_required
from accounts.restriction import blocked_notice
from zones.views import MAX_ZONE_ID, NYC_TZ, _parse_int

from . import interest, messaging, my_rides, reporting
from .forms import (
    ContentReportForm,
    RideMessageForm,
    RidePostEditForm,
    RidePostForm,
    RideSearchForm,
    requested_departure,
)
from .models import RideInterest, RidePost
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
    # US47 #121: a restricted account sees why instead of the form.
    if restricted := blocked_notice(request.user):
        return render(request, "rides/post_ride.html", {"restricted": restricted})

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


def _safe_next(request, fallback):
    """The posted `next` page if it is on this site, else `fallback`."""
    next_page = request.POST.get("next", "")
    if next_page and url_has_allowed_host_and_scheme(
        next_page,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_page
    return fallback


@login_required
@display_name_required
@require_GET
def ride_detail(request, post_id):
    """The post as riders see it. Its owner can always open it; other riders
    while it is open, or once they have shown interest (US33 #95), where
    they also see "I'm interested" or their status and "Withdraw"."""
    post = get_object_or_404(
        RidePost.objects.with_seat_counts().select_related(
            "owner__profile", "pickup_zone", "dropoff_zone"
        ),
        pk=post_id,
    )
    now = timezone.now()
    if not interest.can_view(post, request.user, now):
        raise Http404
    is_owner = post.owner_id == request.user.pk
    viewer_interest = (
        None
        if is_owner
        else interest.interests_of(request.user, [post.pk]).get(post.pk)
    )
    interested_riders = []
    accepted_rider_names = []
    can_accept_interests = False
    if is_owner:
        interested_riders = [
            {
                "interest": rider_interest,
                "rider_name": display_name_of(rider_interest.rider)
                or f"Rider {rider_interest.rider_id}",
                "new": rider_interest.owner_seen_at is None,
            }
            for rider_interest in post.interests.select_related("rider__profile").all()
        ]
        # US37 #99: the owner has now seen these riders (clears the nav badge).
        my_rides.mark_interests_seen(post, now)
        can_accept_interests = (
            post.status == RidePost.OPEN
            and not post.is_expired(now)
            and post.seats_left() > 0
        )
    elif viewer_interest and viewer_interest.status == RideInterest.ACCEPTED:
        accepted_rider_names = [
            display_name_of(rider_interest.rider) or f"Rider {rider_interest.rider_id}"
            for rider_interest in RideInterest.objects.filter(
                post=post, status=RideInterest.ACCEPTED
            )
            .exclude(rider=request.user)
            .select_related("rider__profile")
        ]
    return render(
        request,
        "rides/ride_detail.html",
        {
            "post": post,
            "owner_name": display_name_of(post.owner),
            "status": post.status_label(now),
            "is_owner": is_owner,
            "interest": viewer_interest,
            "can_show_interest": not is_owner
            and interest.blocked_reason(post, request.user, now) is None,
            "interested_riders": interested_riders,
            "can_accept_interests": can_accept_interests,
            "can_undo_interests": not post.is_expired(now),
            "accepted_rider_names": accepted_rider_names,
            "can_edit": is_owner
            and post.status == RidePost.OPEN
            and post.departure_at > now,
            "can_close": is_owner and post.status != RidePost.CLOSED,
            # US38 #101: only shown to the reporter, never to the owner.
            "reported": not is_owner
            and reporting.already_reported(request.user, post=post),
        },
    )


@login_required
@display_name_required
@require_http_methods(["GET", "POST"])
def edit_ride(request, post_id):
    post = get_object_or_404(
        RidePost,
        pk=post_id,
        owner=request.user,
        status=RidePost.OPEN,
        departure_at__gt=timezone.now(),
    )
    # US47 #121: editing a post changes what other riders read, like posting.
    if restricted := blocked_notice(request.user):
        messages.error(request, restricted)
        return redirect("rides:ride_detail", post_id=post.pk)
    if request.method == "POST":
        form = RidePostEditForm(request.user, request.POST, instance=post)
        if form.is_valid() and (saved := form.save()) is not None:
            messages.success(request, "Your shared ride was updated.")
            return redirect("rides:ride_detail", post_id=saved.pk)
    else:
        form = RidePostEditForm(request.user, instance=post)
    return render(request, "rides/edit_ride.html", {"post": post, "form": form})


@login_required
@display_name_required
@require_POST
def close_ride(request, post_id):
    with transaction.atomic():
        post = get_object_or_404(
            RidePost.objects.select_for_update(), pk=post_id, owner=request.user
        )
        if post.status in (RidePost.DELETED, RidePost.REMOVED):
            raise Http404
        if post.status != RidePost.CLOSED:
            post.status = RidePost.CLOSED
            post.save(update_fields=["status"])
    messages.success(request, "Your shared ride was closed.")
    return redirect("rides:ride_detail", post_id=post.pk)


@login_required
@display_name_required
@require_http_methods(["GET", "POST"])
def delete_ride(request, post_id):
    post = get_object_or_404(RidePost, pk=post_id, owner=request.user)
    if post.status in (RidePost.DELETED, RidePost.REMOVED):
        raise Http404
    if request.method == "POST":
        with transaction.atomic():
            post = get_object_or_404(
                RidePost.objects.select_for_update(), pk=post_id, owner=request.user
            )
            if post.status in (RidePost.DELETED, RidePost.REMOVED):
                raise Http404
            post.status = RidePost.DELETED
            post.note = ""
            post.save(update_fields=["status", "note"])
        messages.success(request, "Your shared ride was deleted.")
        return redirect("rides:find_rides")
    return render(request, "rides/delete_ride.html", {"post": post})


# ---- US33 #95: show interest ----


@login_required
@display_name_required
@require_POST
def show_interest(request, post_id):
    if restricted := blocked_notice(request.user):  # US47 #121
        messages.error(request, restricted)
        return redirect(_safe_next(request, reverse("rides:find_rides")))
    post, saved, message = interest.show_interest(request.user, post_id, timezone.now())
    if message in interest.BLOCKED:
        messages.error(request, message)
        return redirect(_safe_next(request, reverse("rides:find_rides")))
    (messages.success if saved else messages.info)(request, message)
    return redirect(_safe_next(request, post_detail_url(post)))


@login_required
@display_name_required
@require_POST
def withdraw_interest(request, post_id):
    post, message = interest.withdraw_interest(request.user, post_id)
    if message == interest.WITHDRAWN:
        messages.success(request, message)
    else:
        messages.info(request, message)
    fallback = (
        post_detail_url(post)
        if interest.can_view(post, request.user, timezone.now())
        else reverse("rides:find_rides")
    )
    return redirect(_safe_next(request, fallback))


def _owner_interest_action(request, post_id, interest_id, action):
    post, changed, message = interest.manage_owner_interest(
        request.user, post_id, interest_id, action
    )
    (messages.success if changed else messages.info)(request, message)
    return redirect(post_detail_url(post))


@login_required
@display_name_required
@require_POST
def accept_interest(request, post_id, interest_id):
    return _owner_interest_action(request, post_id, interest_id, "accept")


@login_required
@display_name_required
@require_POST
def decline_interest(request, post_id, interest_id):
    return _owner_interest_action(request, post_id, interest_id, "decline")


@login_required
@display_name_required
@require_POST
def undo_acceptance(request, post_id, interest_id):
    return _owner_interest_action(request, post_id, interest_id, "undo")


def post_detail_url(post):
    return reverse("rides:ride_detail", args=[post.pk])


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
    context["next"] = request.get_full_path()
    context["my_posts"] = (
        RidePost.objects.with_seat_counts()
        .filter(owner=request.user, departure_at__gt=now)
        .exclude(status__in=[RidePost.CLOSED, RidePost.DELETED, RidePost.REMOVED])
        .select_related("pickup_zone", "dropoff_zone")
        # Explicit: Django drops Meta.ordering in a GROUP BY query (the seat
        # count), so without this the order of equal departures was up to
        # the database (it differed between PostgreSQL 14 on Travis and 16).
        .order_by("departure_at", "pk")
    )
    return render(request, "rides/find_rides.html", context)


# ---- US37 #99: My rides ----


@login_required
@display_name_required
@require_GET
def my_rides_view(request):
    """The rider's own posts and the rides they've asked to join, each with
    its status and unread messages. Rides that left more than 7 days ago are
    hidden unless ?past=1 ("Show past rides")."""
    context = my_rides.build(
        request.user, timezone.now(), show_past=request.GET.get("past") == "1"
    )
    return render(request, "rides/my_rides.html", context)


# ---- US36 #98: message riders about a shared ride ----


def conversation_url(post_id, rider_id):
    return reverse("rides:conversation", args=[post_id, rider_id])


@login_required
@display_name_required
@require_http_methods(["GET", "POST"])
def conversation(request, post_id, rider_id):
    """The owner and one interested rider: messages oldest first and a send
    box. Anyone else gets 404. The page checks for new messages every 15
    seconds while it is visible (rides/js/conversation.js)."""
    talk = messaging.conversation_for(request.user, post_id, rider_id)
    now = timezone.now()
    # US47 #121: a restricted account can read but not send.
    restricted = blocked_notice(request.user, now)
    if request.method == "POST":
        form = RideMessageForm(request.POST)
        if restricted:
            form.add_error(None, restricted)
        elif form.is_valid():
            sent, message = messaging.send(
                request.user, talk, form.cleaned_data["text"], now
            )
            if sent:
                return redirect(f"{conversation_url(post_id, rider_id)}#latest")
            form.add_error(None, message)
    else:
        form = RideMessageForm()
    thread = list(talk.messages())
    messaging.mark_read(thread, request.user, now)
    other = talk.other(request.user)
    reported = reporting.reported_message_ids(request.user, [m.pk for m in thread])
    return render(
        request,
        "rides/conversation.html",
        {
            "post": talk.post,
            "other_name": display_name_of(other) or f"Rider {other.pk}",
            "thread": [
                {**messaging.as_json(m, request.user), "reported": m.pk in reported}
                for m in thread
            ],
            # The page script swaps the 0 for each new message's id.
            "report_url": reverse("rides:report_message", args=[0]),
            "last_id": thread[-1].pk if thread else 0,
            "read_only": talk.read_only_reason(now) or restricted,
            "form": form,
            "poll_url": reverse("rides:conversation_updates", args=[post_id, rider_id]),
            "poll_ms": messaging.POLL_SECONDS * 1000,
            "can_open_post": interest.can_view(talk.post, request.user, now),
        },
    )


@login_required
@require_GET
def conversation_updates(request, post_id, rider_id):
    """JSON: messages newer than ?after=<id>, and whether the conversation
    has become read-only. Polled by the conversation page."""
    talk = messaging.conversation_for(request.user, post_id, rider_id)
    now = timezone.now()
    after = _parse_int(request.GET.get("after"), 0, 2**31 - 1) or 0
    new = list(talk.messages().filter(pk__gt=after))
    messaging.mark_read(new, request.user, now)
    return JsonResponse(
        {
            "messages": [messaging.as_json(m, request.user) for m in new],
            "hidden_ids": list(
                talk.messages().filter(hidden=True).values_list("pk", flat=True)
            ),
            "read_only": talk.read_only_reason(now)
            or blocked_notice(request.user, now),
        }
    )


# ---- US38 #101: report a post or message ----


def _report(request, template_context, back, post=None, message=None):
    if reporting.already_reported(request.user, post=post, message=message):
        if request.method == "POST":
            messages.info(request, reporting.ALREADY)
            return redirect(back)
        return render(
            request,
            "rides/report.html",
            {**template_context, "already": reporting.ALREADY, "back": back},
        )
    form = ContentReportForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        saved = reporting.report(
            request.user, data["reason"], data["note"], post=post, message=message
        )
        messages.success(request, reporting.THANKS if saved else reporting.ALREADY)
        return redirect(back)
    return render(
        request,
        "rides/report.html",
        {**template_context, "form": form, "back": back},
    )


@login_required
@display_name_required
@require_http_methods(["GET", "POST"])
def report_post(request, post_id):
    """A rider who can see a post (not its owner) reports it to the admins."""
    post = reporting.post_to_report(request.user, post_id, timezone.now())
    return _report(
        request,
        {"kind": "post", "post": post, "owner_name": display_name_of(post.owner)},
        post_detail_url(post),
        post=post,
    )


@login_required
@display_name_required
@require_http_methods(["GET", "POST"])
def report_message(request, message_id):
    """The receiver of a message reports it to the admins."""
    message = reporting.message_to_report(request.user, message_id)
    rider_id = (
        message.receiver_id
        if message.sender_id == message.post.owner_id
        else message.sender_id
    )
    return _report(
        request,
        {
            "kind": "message",
            "message": message,
            "post": message.post,
            "sender_name": display_name_of(message.sender)
            or f"Rider {message.sender_id}",
        },
        conversation_url(message.post_id, rider_id),
        message=message,
    )
