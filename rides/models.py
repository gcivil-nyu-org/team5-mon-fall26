from django.conf import settings
from django.db import models
from django.db.models import F, Q
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


class RidePost(models.Model):
    """US31 #93: a rider taking a taxi from one zone to another at a time,
    offering seats to riders going the same way. Zones only, no address."""

    OPEN = "open"
    FULL = "full"
    CLOSED = "closed"
    STATUS_CHOICES = [(OPEN, "Open"), (FULL, "Full"), (CLOSED, "Closed")]
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
    status = models.CharField(max_length=6, choices=STATUS_CHOICES, default=OPEN)
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
                condition=Q(status__in=["open", "full", "closed"]),
                name="ride_post_status_valid",
            ),
        ]

    def is_expired(self, now=None):
        """Departed and not closed by its owner."""
        now = now or timezone.now()
        return self.status != self.CLOSED and self.departure_at <= now

    def seats_left(self):
        """Seats still free. Accepting riders (US34 #96) will lower it; until
        then it is the seats offered."""
        return self.seats

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
