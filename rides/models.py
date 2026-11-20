from django.conf import settings
from django.db import models
from django.db.models import Count, F, Q
from django.utils import timezone

from zones.models import Zone
from zones.views import NYC_TZ

MAX_OPEN_POSTS = 3
MAX_SEATS = 3
NOTE_MAX_LENGTH = 200


class RidePostQuerySet(models.QuerySet):
    def open(self, now=None):
        """Open and not yet departed. Expiry is worked out when posts are
        read, so no scheduled job has to change the status."""
        return self.filter(status=RidePost.OPEN, departure_at__gt=now or timezone.now())

    def with_seat_counts(self):
        """Include the number of accepted riders for list and detail pages."""
        return self.annotate(
            accepted_interest_count=Count(
                "interests", filter=Q(interests__status=RideInterest.ACCEPTED)
            )
        )


class RidePost(models.Model):
    """US31 #93: a rider taking a taxi from one zone to another at a time,
    offering seats to riders going the same way. Zones only, no address."""

    OPEN = "open"
    FULL = "full"
    CLOSED = "closed"
    DELETED = "deleted"
    REMOVED = "removed"
    STATUS_CHOICES = [
        (OPEN, "Open"),
        (FULL, "Full"),
        (CLOSED, "Closed"),
        (DELETED, "Deleted"),
        (REMOVED, "Removed by a moderator"),
    ]
    EXPIRED = "Expired"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # deleting the account deletes the posts
        related_name="ride_posts",
    )
    pickup_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="ride_posts_from"
    )
    dropoff_zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="ride_posts_to"
    )
    departure_at = models.DateTimeField(db_index=True)
    seats = models.PositiveSmallIntegerField()
    note = models.CharField(max_length=NOTE_MAX_LENGTH, blank=True)
    status = models.CharField(max_length=7, choices=STATUS_CHOICES, default=OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RidePostQuerySet.as_manager()

    class Meta:
        ordering = ["departure_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(seats__gte=1, seats__lte=MAX_SEATS),
                name="ride_post_seats_range",
            ),
            models.CheckConstraint(
                condition=~Q(pickup_zone=F("dropoff_zone")),
                name="ride_post_different_zones",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=["open", "full", "closed", "deleted", "removed"]
                ),
                name="ride_post_status_valid",
            ),
        ]

    def is_expired(self, now=None):
        """Departed and not closed by its owner."""
        now = now or timezone.now()
        return (
            self.status not in (self.CLOSED, self.DELETED, self.REMOVED)
            and self.departure_at <= now
        )

    def seats_left(self):
        """Seats offered minus the riders the owner has accepted."""
        accepted = getattr(self, "accepted_interest_count", None)
        if accepted is None:
            accepted = self.interests.filter(status=RideInterest.ACCEPTED).count()
        return max(0, self.seats - accepted)

    def status_label(self, now=None):
        """ "Open", "Full", "Closed" or "Expired", as riders see it."""
        return self.EXPIRED if self.is_expired(now) else self.get_status_display()

    def __str__(self):
        departure = timezone.localtime(self.departure_at, NYC_TZ)
        return (
            f"{self.pickup_zone.name} → {self.dropoff_zone.name} at "
            f"{departure:%Y-%m-%d %H:%M} ({self.status_label()})"
        )


class RideInterest(models.Model):
    """US33 #95: a rider telling a post's owner they'd like to share the
    ride. One per rider per post. The owner accepts or declines it in US34."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (ACCEPTED, "Accepted"),
        (DECLINED, "Declined"),
    ]

    post = models.ForeignKey(
        RidePost,
        on_delete=models.CASCADE,  # deleting the post (or its owner) deletes it
        related_name="interests",
    )
    rider = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # deleting the rider's account deletes it
        related_name="ride_interests",
    )
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    # US37 #99: when the owner first opened the post page after this interest
    # arrived. Empty means "new" for the My rides badge.
    owner_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["post", "rider"], name="ride_interest_once_per_rider"
            ),
            models.CheckConstraint(
                condition=Q(status__in=["pending", "accepted", "declined"]),
                name="ride_interest_status_valid",
            ),
        ]

    def __str__(self):
        from accounts.display_name import display_name_of

        name = display_name_of(self.rider) or f"rider {self.rider_id}"
        return f"{name}: {self.get_status_display()}"


MESSAGE_MAX_LENGTH = 500


class RideMessage(models.Model):
    """US36 #98: a message between a post's owner and one interested rider.
    The conversation is the post plus that pair of riders."""

    post = models.ForeignKey(
        RidePost,
        on_delete=models.CASCADE,  # removing the post row removes its messages
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # deleting the account deletes what it sent
        related_name="ride_messages_sent",
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # deleting the account deletes what it received
        related_name="ride_messages_received",
    )
    text = models.CharField(max_length=MESSAGE_MAX_LENGTH)
    hidden = models.BooleanField(default=False, db_default=False)
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sent_at", "pk"]
        indexes = [
            # The 30-per-hour limit counts a sender's recent messages.
            models.Index(fields=["sender", "sent_at"], name="ride_message_sender_sent"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(sender=F("receiver")),
                name="ride_message_not_to_self",
            ),
            models.CheckConstraint(
                condition=~Q(text=""),
                name="ride_message_not_empty",
            ),
        ]

    def __str__(self):
        return f"Message {self.pk} on post {self.post_id}"


REPORT_NOTE_MAX_LENGTH = 300


class ContentReport(models.Model):
    """US38 #101: a rider reporting a post or a message to the admins. Only
    admins see reports; the reported rider is never told who reported them."""

    SPAM = "spam"
    UNSAFE = "unsafe"
    OFFENSIVE = "offensive"
    OTHER = "other"
    REASON_CHOICES = [
        (SPAM, "Spam"),
        (UNSAFE, "Unsafe"),
        (OFFENSIVE, "Offensive"),
        (OTHER, "Other"),
    ]
    OPEN = "open"
    CLOSED = "closed"
    STATUS_CHOICES = [(OPEN, "Open"), (CLOSED, "Closed")]
    CONTENT_REMOVED = "removed"
    NO_ACTION = "no_action"
    OUTCOME_CHOICES = [
        (CONTENT_REMOVED, "Content removed"),
        (NO_ACTION, "No action needed"),
    ]

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # deleting the account deletes its reports
        related_name="content_reports",
    )
    # Exactly one of post and message is set.
    post = models.ForeignKey(
        RidePost,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reports",
    )
    message = models.ForeignKey(
        RideMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reports",
    )
    reason = models.CharField(max_length=9, choices=REASON_CHOICES)
    note = models.CharField(max_length=REPORT_NOTE_MAX_LENGTH, blank=True)
    # What the reported post or message said when it was reported, so admins
    # still see it if the owner edits the note or deletes the post.
    reported_text = models.TextField(blank=True)
    status = models.CharField(max_length=6, choices=STATUS_CHOICES, default=OPEN)
    outcome = models.CharField(
        max_length=9, choices=OUTCOME_CHOICES, blank=True, default="", db_default=""
    )
    closed_by = models.CharField(max_length=150, blank=True, default="", db_default="")
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(post__isnull=False, message__isnull=True)
                | Q(post__isnull=True, message__isnull=False),
                name="content_report_post_or_message",
            ),
            models.UniqueConstraint(
                fields=["reporter", "post"],
                condition=Q(post__isnull=False),
                name="content_report_once_per_post",
            ),
            models.UniqueConstraint(
                fields=["reporter", "message"],
                condition=Q(message__isnull=False),
                name="content_report_once_per_message",
            ),
            models.CheckConstraint(
                condition=Q(reason__in=["spam", "unsafe", "offensive", "other"]),
                name="content_report_reason_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["open", "closed"]),
                name="content_report_status_valid",
            ),
        ]

    @property
    def kind(self):
        return "Post" if self.post_id else "Message"

    @property
    def reported_user(self):
        return self.post.owner if self.post_id else self.message.sender

    def __str__(self):
        target = (
            f"post {self.post_id}" if self.post_id else f"message {self.message_id}"
        )
        return f"Report {self.pk}: {target} ({self.get_reason_display()})"
