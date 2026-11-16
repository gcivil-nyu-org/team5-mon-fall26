"""US38 #101: report a post or a message that is unsafe or inappropriate.
Only admins see reports (Django admin until Epic 5 adds moderation)."""

from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from zones.views import NYC_TZ

from . import interest
from .models import ContentReport, RideMessage, RidePost

THANKS = (
    "Thanks for your report. An admin will look at it. The rider you reported "
    "is never told who reported them."
)
ALREADY = "You've already reported this."


def post_to_report(user, post_id, now):
    """A post `user` may report: one they can see that isn't their own.
    404 otherwise (deleted posts, other riders' posts they can't open, and
    their own posts)."""
    post = get_object_or_404(
        RidePost.objects.select_related("owner", "pickup_zone", "dropoff_zone"),
        pk=post_id,
    )
    if post.owner_id == user.pk or not interest.can_view(post, user, now):
        raise Http404
    return post


def message_to_report(user, message_id):
    """A message sent to `user`. Their own messages, and messages between
    other riders, are 404."""
    return get_object_or_404(
        RideMessage.objects.select_related(
            "post__pickup_zone", "post__dropoff_zone", "sender"
        ),
        pk=message_id,
        receiver=user,
    )


def already_reported(user, post=None, message=None):
    if post is not None:
        return ContentReport.objects.filter(reporter=user, post=post).exists()
    return ContentReport.objects.filter(reporter=user, message=message).exists()


def reported_message_ids(user, message_ids):
    return set(
        ContentReport.objects.filter(
            reporter=user, message_id__in=message_ids
        ).values_list("message_id", flat=True)
    )


def snapshot(post=None, message=None):
    """The reported content as it is now, for the admin."""
    if message is not None:
        return message.text
    departure = timezone.localtime(post.departure_at, NYC_TZ)
    return (
        f"{post.pickup_zone.name} to {post.dropoff_zone.name}, "
        f"{departure:%Y-%m-%d %H:%M}, {post.seats} seat(s). "
        f"Note: {post.note or '(none)'}"
    )


def report(user, reason, note, post=None, message=None):
    """Save the report. Returns False if `user` already reported this item
    (the unique index also stops two reports sent at the same moment)."""
    try:
        with transaction.atomic():
            ContentReport.objects.create(
                reporter=user,
                post=post,
                message=message,
                reason=reason,
                note=note,
                reported_text=snapshot(post, message),
            )
    except IntegrityError:
        return False
    return True
