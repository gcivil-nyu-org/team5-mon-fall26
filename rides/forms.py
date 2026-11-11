import re
from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from reports.forms import NycDateTimeField
from zones.models import Zone
from zones.views import NYC_TZ, shape_zone_ids

from .models import MAX_OPEN_POSTS, MAX_SEATS, NOTE_MAX_LENGTH, RidePost

MAX_DAYS_AHEAD = 14
STEP_MINUTES = 15

SAME_ZONES = "Choose a dropoff zone that is different from the pickup zone."
DEPARTURE_REQUIRED = "Enter the departure date and time."
DEPARTURE_PAST = "Choose a departure time in the future."
DEPARTURE_TOO_FAR = (
    f"Choose a departure time in the next {MAX_DAYS_AHEAD} days. "
    "You can post rides up to 2 weeks ahead."
)
DEPARTURE_STEP = "Choose a departure time on the quarter hour (:00, :15, :30 or :45)."
NOTE_TOO_LONG = f"Keep the note to {NOTE_MAX_LENGTH} characters or fewer."
NOTE_CONTACT = (
    "Remove the email address or phone number from the note. "
    "Other riders will see it."
)
TOO_MANY_OPEN = (
    f"You already have {MAX_OPEN_POSTS} open shared rides, the most you can have "
    "at a time. You can post another once one of them has departed."
)

# Contact details riders might put in the note by mistake: an email address,
# or a phone number (10 or more digits, with or without separators).
EMAIL_IN_TEXT = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
PHONE_IN_TEXT = re.compile(r"(?:\d[\s().+-]*){10,}")


def _quarter_floor(moment):
    moment = moment.replace(second=0, microsecond=0)
    return moment - timedelta(minutes=moment.minute % STEP_MINUTES)


def first_departure(now):
    """The earliest departure allowed: the first quarter hour after now."""
    return _quarter_floor(now.astimezone(NYC_TZ)) + timedelta(minutes=STEP_MINUTES)


def last_departure(now):
    """The latest departure allowed: the last quarter hour within 14 days."""
    return _quarter_floor(now.astimezone(NYC_TZ) + timedelta(days=MAX_DAYS_AHEAD))


def default_departure(now):
    """What the form starts at: a quarter hour at least 15 minutes away, so
    there is time to fill in the form before it passes."""
    soon = now.astimezone(NYC_TZ) + timedelta(minutes=STEP_MINUTES)
    floor = _quarter_floor(soon)
    return floor if floor == soon else floor + timedelta(minutes=STEP_MINUTES)


def open_posts(user, now):
    return RidePost.objects.open(now).filter(owner=user).count()


class RidePostForm(forms.ModelForm):
    """US31 #93: "Post a shared ride". The owner and the status are set
    here, never taken from the request."""

    departure_at = NycDateTimeField(
        label="Departure date and time (New York time)",
        error_messages={"required": DEPARTURE_REQUIRED},
    )
    seats = forms.TypedChoiceField(
        label="Seats offered",
        choices=[(n, str(n)) for n in range(1, MAX_SEATS + 1)],
        coerce=int,
        initial=1,
        help_text="How many other riders can join you.",
    )
    note = forms.CharField(
        label="Note (optional)",
        required=False,
        max_length=NOTE_MAX_LENGTH,
        error_messages={"max_length": NOTE_TOO_LONG},
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Don't include addresses, phone numbers, email addresses or "
        "other contact details. Other riders will see this note.",
    )

    class Meta:
        model = RidePost
        fields = ["pickup_zone", "dropoff_zone", "departure_at", "seats", "note"]
        labels = {"pickup_zone": "Pickup zone", "dropoff_zone": "Dropoff zone"}

    def __init__(self, user, *args, now=None, **kwargs):
        self.user = user
        self.now = now or timezone.now()
        super().__init__(*args, **kwargs)
        on_map = Zone.objects.filter(zone_id__in=shape_zone_ids()).order_by(
            "borough", "name"
        )
        for name in ("pickup_zone", "dropoff_zone"):
            self.fields[name].queryset = on_map
            self.fields[name].label_from_instance = (
                lambda zone: f"{zone.name} ({zone.borough})"
            )
        self.fields["departure_at"].widget.attrs.update(
            {
                "step": str(STEP_MINUTES * 60),
                "min": f"{first_departure(self.now):%Y-%m-%dT%H:%M}",
                "max": f"{last_departure(self.now):%Y-%m-%dT%H:%M}",
            }
        )

    def clean_departure_at(self):
        departure = self.cleaned_data["departure_at"]
        if departure <= self.now:
            raise forms.ValidationError(DEPARTURE_PAST)
        if departure > self.now + timedelta(days=MAX_DAYS_AHEAD):
            raise forms.ValidationError(DEPARTURE_TOO_FAR)
        local = departure.astimezone(NYC_TZ)
        if local.minute % STEP_MINUTES or local.second or local.microsecond:
            raise forms.ValidationError(DEPARTURE_STEP)
        return departure

    def clean_note(self):
        note = self.cleaned_data["note"]
        if EMAIL_IN_TEXT.search(note) or PHONE_IN_TEXT.search(note):
            raise forms.ValidationError(NOTE_CONTACT)
        return note

    def clean(self):
        cleaned = super().clean()
        pickup = cleaned.get("pickup_zone")
        if pickup is not None and pickup == cleaned.get("dropoff_zone"):
            self.add_error("dropoff_zone", SAME_ZONES)
        if open_posts(self.user, self.now) >= MAX_OPEN_POSTS:
            raise forms.ValidationError(TOO_MANY_OPEN)
        return cleaned

    def save(self):
        """Save as an open post of this user. Returns None if the user
        reached the limit meanwhile: the count runs again with the user's
        row locked, so two posts sent at once can't make a 4th."""
        post = super().save(commit=False)
        post.owner = self.user
        post.status = RidePost.OPEN
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=self.user.pk)
            if open_posts(self.user, self.now) >= MAX_OPEN_POSTS:
                self.add_error(None, TOO_MANY_OPEN)
                return None
            post.save()
        return post
