"""US33 #95: show or withdraw interest in a shared ride."""

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404

from .models import RideInterest, RidePost

SHOWN = (
    "You're interested in this ride. The owner will see your display name, "
    "never your email address."
)
ALREADY = "You've already shown interest in this ride."
OWN_POST = "You can't show interest in your own shared ride."
FULL = "This shared ride is full."
CLOSED = "This shared ride is closed."
EXPIRED = "This shared ride has already left."
WITHDRAWN = "Your interest was withdrawn."
DECLINED_STAYS = (
    "The owner declined your interest, so it can't be withdrawn or sent again."
)
NOTHING_TO_WITHDRAW = "You haven't shown interest in this ride."
BLOCKED = frozenset({OWN_POST, FULL, CLOSED, EXPIRED})


def _existing(post, rider):
    return RideInterest.objects.filter(post=post, rider=rider)


def blocked_reason(post, rider, now):
    """Why the rider can't show interest in the post, or None."""
    if post.owner_id == rider.pk:
        return OWN_POST
    if post.status == RidePost.CLOSED:
        return CLOSED
    if post.is_expired(now):
        return EXPIRED
    if post.status == RidePost.FULL:
        return FULL
    return None


def show_interest(rider, post_id, now):
    """Save a pending interest. Returns (post, saved, message). The post row
    is locked, so the checks and the save see the same post; the unique
    index stops a second interest sent at the same moment."""
    with transaction.atomic():
        post = get_object_or_404(RidePost.objects.select_for_update(), pk=post_id)
        reason = blocked_reason(post, rider, now)
        if reason is not None:
            return post, False, reason
        if _existing(post, rider).exists():
            return post, False, ALREADY
        try:
            with transaction.atomic():
                RideInterest.objects.create(post=post, rider=rider)
        except IntegrityError:
            return post, False, ALREADY
    return post, True, SHOWN


def withdraw_interest(rider, post_id):
    """Delete the rider's pending or accepted interest. Returns (post,
    message). A declined interest stays, so it can't be sent again."""
    post = get_object_or_404(RidePost, pk=post_id)
    interest = _existing(post, rider).first()
    if interest is None:
        return post, NOTHING_TO_WITHDRAW
    if interest.status == RideInterest.DECLINED:
        return post, DECLINED_STAYS
    interest.delete()
    return post, WITHDRAWN


def interests_of(rider, post_ids):
    """The rider's interests in these posts, by post id."""
    return {
        interest.post_id: interest
        for interest in RideInterest.objects.filter(rider=rider, post_id__in=post_ids)
    }


def can_view(post, user, now):
    """The owner always; other riders while the post is open, or once they
    have shown interest in it (so they keep seeing their status)."""
    if post.owner_id == user.pk:
        return True
    if post.status == RidePost.OPEN and not post.is_expired(now):
        return True
    return _existing(post, user).exists()
