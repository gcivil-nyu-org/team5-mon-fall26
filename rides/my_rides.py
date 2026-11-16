"""US37 #99: "My rides", the rider's own posts and the rides they've asked
to join on one page, with unread messages and new interested riders."""

from dataclasses import dataclass, field
from datetime import timedelta
from functools import cached_property

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.urls import reverse

from accounts.display_name import display_name_of

from .models import RideInterest, RideMessage, RidePost

PAST_AFTER = timedelta(days=7)
WITHDRAWN = "Withdrawn"


def _name(user):
    return display_name_of(user) or f"Rider {user.pk}"


def _conversation_url(post_id, rider_id):
    return reverse("rides:conversation", args=[post_id, rider_id])


def unread_counts(user):
    """{(post_id, sender_id): unread messages sent to `user`}."""
    rows = (
        RideMessage.objects.filter(receiver=user, read_at__isnull=True)
        .values("post_id", "sender_id")
        .annotate(n=Count("pk"))
    )
    return {(r["post_id"], r["sender_id"]): r["n"] for r in rows}


def badge_count(user):
    """Unread messages plus new interested riders, for the nav badge. The
    owner's deleted posts are left out, as they are on My rides."""
    unread = (
        RideMessage.objects.filter(receiver=user, read_at__isnull=True)
        .exclude(post__owner=user, post__status=RidePost.DELETED)
        .count()
    )
    new_riders = (
        RideInterest.objects.filter(post__owner=user, owner_seen_at__isnull=True)
        .exclude(post__status=RidePost.DELETED)
        .count()
    )
    return unread + new_riders


class Badge:
    """Counted once per request, and only if a template shows it."""

    def __init__(self, user):
        self.user = user

    @cached_property
    def count(self):
        return badge_count(self.user)


def mark_interests_seen(post, now):
    """The owner opened the post page: its interested riders are not new."""
    RideInterest.objects.filter(post=post, owner_seen_at__isnull=True).update(
        owner_seen_at=now
    )


@dataclass
class RiderRow:
    name: str
    status: str
    new: bool
    unread: int
    url: str


@dataclass
class MyPost:
    post: RidePost
    status: str
    seats_left: int
    riders: list = field(default_factory=list)

    @property
    def unread(self):
        return sum(r.unread for r in self.riders)

    @property
    def new_riders(self):
        return sum(r.new for r in self.riders)


@dataclass
class AskedRide:
    post: RidePost
    owner_name: str
    status: str
    unread: int
    url: str
    detail_url: str | None

    @property
    def new_riders(self):
        return 0


def asked_status(post, interest):
    """Pending, Accepted or Declined; Closed or Deleted once the owner has
    closed or deleted the post; Withdrawn if the rider took their interest
    back but the two have messages."""
    if post.status == RidePost.DELETED:
        return "Deleted"
    if post.status == RidePost.CLOSED:
        return "Closed"
    if interest is None:
        return WITHDRAWN
    return interest.get_status_display()


def _message_partners(user, posts_q):
    """{(post_id, other_user_id)} for every conversation `user` has messages in."""
    rows = (
        RideMessage.objects.filter(posts_q)
        .filter(Q(sender=user) | Q(receiver=user))
        .values_list("post_id", "sender_id", "receiver_id")
        .distinct()
    )
    return {(p, r if s == user.pk else s) for p, s, r in rows}


def my_posts(user, now, unread):
    posts = list(
        RidePost.objects.with_seat_counts()
        .filter(owner=user)
        .exclude(status=RidePost.DELETED)
        .select_related("pickup_zone", "dropoff_zone")
    )
    rows = {p.pk: MyPost(p, p.status_label(now), p.seats_left()) for p in posts}
    seen = set()
    for i in RideInterest.objects.filter(post__in=posts).select_related(
        "rider__profile"
    ):
        seen.add((i.post_id, i.rider_id))
        rows[i.post_id].riders.append(
            RiderRow(
                name=_name(i.rider),
                status=i.get_status_display(),
                new=i.owner_seen_at is None,
                unread=unread.get((i.post_id, i.rider_id), 0),
                url=_conversation_url(i.post_id, i.rider_id),
            )
        )
    # Riders who withdrew but have messages with the owner can still be read.
    gone = _message_partners(user, Q(post__in=posts)) - seen
    users = get_user_model().objects.select_related("profile")
    others = users.in_bulk({other for _, other in gone})
    for post_id, other in sorted(gone):
        rows[post_id].riders.append(
            RiderRow(
                name=_name(others[other]),
                status=WITHDRAWN,
                new=False,
                unread=unread.get((post_id, other), 0),
                url=_conversation_url(post_id, other),
            )
        )
    return list(rows.values())


def asked_rides(user, now, unread):
    interests = {
        i.post_id: i
        for i in RideInterest.objects.filter(rider=user).select_related(
            "post__owner__profile", "post__pickup_zone", "post__dropoff_zone"
        )
    }
    posts = {pid: i.post for pid, i in interests.items()}
    gone = {
        post_id
        for post_id, _ in _message_partners(user, ~Q(post__owner=user))
        if post_id not in posts
    }
    posts.update(
        RidePost.objects.select_related(
            "owner__profile", "pickup_zone", "dropoff_zone"
        ).in_bulk(gone)
    )
    rows = []
    for post in posts.values():
        status = asked_status(post, interests.get(post.pk))
        rows.append(
            AskedRide(
                post=post,
                owner_name=_name(post.owner),
                status=status,
                unread=unread.get((post.pk, post.owner_id), 0),
                url=_conversation_url(post.pk, user.pk),
                detail_url=(
                    None
                    if status in ("Deleted", WITHDRAWN)
                    else reverse("rides:ride_detail", args=[post.pk])
                ),
            )
        )
    return rows


def _split(rows, now, show_past):
    """Upcoming first (soonest first), then past (latest first). Rides that
    left more than 7 days ago are hidden unless asked for, but never while
    they have something unread or new."""
    cutoff = now - PAST_AFTER
    shown, hidden = [], 0
    for row in rows:
        old = row.post.departure_at < cutoff
        if old and not show_past and not (row.unread or row.new_riders):
            hidden += 1
        else:
            shown.append(row)
    upcoming = sorted(
        (r for r in shown if r.post.departure_at >= now),
        key=lambda r: (r.post.departure_at, r.post.pk),
    )
    past = sorted(
        (r for r in shown if r.post.departure_at < now),
        key=lambda r: (r.post.departure_at, r.post.pk),
        reverse=True,
    )
    return upcoming + past, hidden


def build(user, now, show_past=False):
    unread = unread_counts(user)
    posts, hidden_posts = _split(my_posts(user, now, unread), now, show_past)
    asked, hidden_asked = _split(asked_rides(user, now, unread), now, show_past)
    return {
        "my_posts": posts,
        "asked_rides": asked,
        "hidden_count": hidden_posts + hidden_asked,
        "show_past": show_past,
    }
