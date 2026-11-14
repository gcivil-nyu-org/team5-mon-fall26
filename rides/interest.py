"""US33 #95: show or withdraw interest in a shared ride."""

from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

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
DELETED = "This shared ride was deleted."
WITHDRAWN = "Your interest was withdrawn."
DECLINED_STAYS = (
    "The owner declined your interest, so it can't be withdrawn or sent again."
)
NOTHING_TO_WITHDRAW = "You haven't shown interest in this ride."
BLOCKED = frozenset({OWN_POST, FULL, CLOSED, EXPIRED, DELETED})
OWNER_ACCEPTED = "Rider accepted."
OWNER_DECLINED = "Rider declined."
ACCEPTANCE_UNDONE = "Acceptance undone. The ride is open again."
ALREADY_ACCEPTED = "This rider is already accepted."
ALREADY_DECLINED = "This rider was already declined."
DECLINED_CANNOT_ACCEPT = "A declined rider can't be accepted."
NOT_PENDING = "Only a pending rider can be declined."
NOT_ACCEPTED = "This rider isn't currently accepted."


def _existing(post, rider):
    return RideInterest.objects.filter(post=post, rider=rider)


def _accepted_count(post):
    return RideInterest.objects.filter(post=post, status=RideInterest.ACCEPTED).count()


def _sync_post_capacity(post):
    """Keep open/full in step with accepted interests. Call with the post locked."""
    accepted = _accepted_count(post)
    if post.status in (RidePost.CLOSED, RidePost.DELETED):
        return accepted
    status = RidePost.FULL if accepted >= post.seats else RidePost.OPEN
    if post.status != status:
        post.status = status
        post.save(update_fields=["status"])
    return accepted


def blocked_reason(post, rider, now):
    """Why the rider can't show interest in the post, or None."""
    if post.owner_id == rider.pk:
        return OWN_POST
    if post.status == RidePost.DELETED:
        return DELETED
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


def manage_owner_interest(owner, post_id, interest_id, action):
    """Accept, decline or undo an interest, serializing seat changes per post."""
    with transaction.atomic():
        post = get_object_or_404(RidePost.objects.select_for_update(), pk=post_id)
        if post.status == RidePost.DELETED:
            raise Http404
        if post.owner_id != owner.pk:
            raise Http404
        rider_interest = get_object_or_404(
            RideInterest.objects.select_for_update(), post=post, pk=interest_id
        )

        if action == "accept":
            if rider_interest.status == RideInterest.ACCEPTED:
                return post, False, ALREADY_ACCEPTED
            if rider_interest.status == RideInterest.DECLINED:
                return post, False, DECLINED_CANNOT_ACCEPT
            if post.status == RidePost.CLOSED:
                return post, False, CLOSED
            if post.is_expired(timezone.now()):
                return post, False, EXPIRED
            if _sync_post_capacity(post) >= post.seats:
                return post, False, FULL
            rider_interest.status = RideInterest.ACCEPTED
            rider_interest.save(update_fields=["status"])
            _sync_post_capacity(post)
            return post, True, OWNER_ACCEPTED

        if action == "decline":
            if rider_interest.status == RideInterest.DECLINED:
                return post, False, ALREADY_DECLINED
            if rider_interest.status != RideInterest.PENDING:
                return post, False, NOT_PENDING
            rider_interest.status = RideInterest.DECLINED
            rider_interest.save(update_fields=["status"])
            return post, True, OWNER_DECLINED

        if action == "undo":
            if rider_interest.status != RideInterest.ACCEPTED:
                return post, False, NOT_ACCEPTED
            rider_interest.status = RideInterest.PENDING
            rider_interest.save(update_fields=["status"])
            _sync_post_capacity(post)
            return post, True, ACCEPTANCE_UNDONE

        raise ValueError(f"Unknown interest action: {action}")


def withdraw_interest(rider, post_id):
    """Delete the rider's pending or accepted interest. Returns (post,
    message). A declined interest stays, so it can't be sent again. Accepted
    riders free their seat, reopening a full post when appropriate."""
    with transaction.atomic():
        post = get_object_or_404(RidePost.objects.select_for_update(), pk=post_id)
        if post.status == RidePost.DELETED:
            raise Http404
        rider_interest = _existing(post, rider).select_for_update().first()
        if rider_interest is None:
            return post, NOTHING_TO_WITHDRAW
        if rider_interest.status == RideInterest.DECLINED:
            return post, DECLINED_STAYS
        was_accepted = rider_interest.status == RideInterest.ACCEPTED
        rider_interest.delete()
        if was_accepted:
            _sync_post_capacity(post)
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
    if post.status == RidePost.DELETED:
        return False
    if post.owner_id == user.pk:
        return True
    if post.status == RidePost.OPEN and not post.is_expired(now):
        return True
    return _existing(post, user).exists()
