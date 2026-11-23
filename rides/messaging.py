"""US36 #98: messages between a post's owner and one interested rider."""

from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import dateformat, timezone

from accounts.display_name import display_name_of
from zones.views import NYC_TZ

from .models import RideInterest, RideMessage, RidePost

POLL_SECONDS = 15
MAX_PER_HOUR = 30
READ_ONLY_AFTER = timedelta(hours=24)

SENT = "Message sent."
TOO_MANY = (
    f"You've sent {MAX_PER_HOUR} messages in the last hour, the most allowed. "
    "Please wait a little before sending another."
)
DELETED = "This conversation is read-only because the shared ride was deleted."
REMOVED = (
    "This conversation is read-only because the shared ride was removed by a moderator."
)
HIDDEN_TEXT = "This message was removed by a moderator"
DEPARTED = (
    "This conversation is read-only because the ride left more than 24 hours ago."
)
DECLINED = "This conversation is read-only because the owner declined this rider."
WITHDRAWN = "This conversation is read-only because the rider is no longer interested."


@dataclass
class Conversation:
    post: RidePost
    owner: object
    rider: object
    interest: RideInterest | None

    def other(self, user):
        return self.rider if user.pk == self.owner.pk else self.owner

    def messages(self):
        return (
            RideMessage.objects.filter(post=self.post)
            .filter(
                Q(sender=self.owner, receiver=self.rider)
                | Q(sender=self.rider, receiver=self.owner)
            )
            .select_related("sender__profile")
        )

    def read_only_reason(self, now):
        """Why nobody can send in this conversation any more, or None."""
        if self.post.status == RidePost.DELETED:
            return DELETED
        if self.post.status == RidePost.REMOVED:
            return REMOVED
        if now >= self.post.departure_at + READ_ONLY_AFTER:
            return DEPARTED
        if self.interest is None:
            return WITHDRAWN
        if self.interest.status == RideInterest.DECLINED:
            return DECLINED
        return None


def conversation_for(user, post_id, rider_id):
    """The conversation on `post_id` between its owner and `rider_id`, if
    `user` is one of the two. 404 for anyone else, for the owner talking to
    themselves, and for a rider who never showed interest (unless the two
    already have messages, so a withdrawn rider can still read them)."""
    post = get_object_or_404(
        RidePost.objects.select_related(
            "owner__profile", "pickup_zone", "dropoff_zone"
        ),
        pk=post_id,
    )
    if rider_id == post.owner_id or user.pk not in (post.owner_id, rider_id):
        raise Http404
    rider = get_object_or_404(
        get_user_model().objects.select_related("profile"), pk=rider_id
    )
    interest = RideInterest.objects.filter(post=post, rider=rider).first()
    conversation = Conversation(post, post.owner, rider, interest)
    if interest is None and not conversation.messages().exists():
        raise Http404
    return conversation


def send(sender, conversation, text, now):
    """Save a message. Returns (sent, message). The sender's user row is
    locked, so two messages sent at the same moment can't both slip past the
    hourly limit; the post row is locked so it can't be deleted mid-send."""
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=sender.pk)
        conversation.post = RidePost.objects.select_for_update().get(
            pk=conversation.post.pk
        )
        conversation.interest = RideInterest.objects.filter(
            post=conversation.post, rider=conversation.rider
        ).first()
        reason = conversation.read_only_reason(now)
        if reason is not None:
            return False, reason
        recent = RideMessage.objects.filter(
            sender=sender, sent_at__gt=now - timedelta(hours=1)
        ).count()
        if recent >= MAX_PER_HOUR:
            return False, TOO_MANY
        RideMessage.objects.create(
            post=conversation.post,
            sender=sender,
            receiver=conversation.other(sender),
            text=text,
        )
    return True, SENT


def mark_read(messages, reader, now):
    """Mark the messages sent to `reader` as read (for US37's unread counts)."""
    ids = [m.pk for m in messages if m.receiver_id == reader.pk and m.read_at is None]
    if ids:
        RideMessage.objects.filter(pk__in=ids).update(read_at=now)


def sent_label(message):
    """When it was sent, in New York time, e.g. "Thu 12 Nov, 9:05 AM"."""
    return dateformat.format(
        timezone.localtime(message.sent_at, NYC_TZ), "D j M, g:i A"
    )


def as_json(message, viewer):
    """A message for the polling endpoint. Display names only, never email."""
    mine = message.sender_id == viewer.pk
    return {
        "id": message.pk,
        "mine": mine,
        "sender": (
            "You"
            if mine
            else display_name_of(message.sender) or f"Rider {message.sender_id}"
        ),
        "text": HIDDEN_TEXT if message.hidden else message.text,
        **({"hidden": True} if message.hidden else {}),
        "sent_at": sent_label(message),
    }
