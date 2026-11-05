from django import forms
from django.utils import timezone

from zones.models import Zone
from zones.views import NYC_TZ, shape_zone_ids

from .models import MAX_FARE, FareReport
from .review import DAILY_LIMIT, MAX_AGE, reports_today, review_status

FARE_NOT_POSITIVE = "Enter a taxi fare above $0."
FARE_TOO_HIGH = "Enter a taxi fare of $500 or less."
QUOTE_NOT_POSITIVE = "Enter a rideshare quote above $0."
QUOTE_TOO_HIGH = "Enter a rideshare quote of $500 or less."
QUOTE_NEEDS_SERVICE = "Choose the rideshare service that gave this quote."
SERVICE_NEEDS_QUOTE = "Enter the price the rideshare service quoted."
RIDE_IN_FUTURE = "The ride time can't be in the future."
RIDE_TOO_OLD = "Report rides from the last 30 days only."
DAILY_LIMIT_REACHED = (
    f"You can submit up to {DAILY_LIMIT} fare reports a day. Try again tomorrow."
)


class NycDateTimeField(forms.DateTimeField):
    """A date and time typed in New York time, whatever TIME_ZONE says."""

    widget = forms.DateTimeInput(
        attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
    )

    def prepare_value(self, value):
        with timezone.override(NYC_TZ):
            return super().prepare_value(value)

    def to_python(self, value):
        with timezone.override(NYC_TZ):
            return super().to_python(value)


def _check_amount(value, not_positive, too_high):
    if value is not None and value <= 0:
        raise forms.ValidationError(not_positive)
    if value is not None and value > MAX_FARE:
        raise forms.ValidationError(too_high)
    return value


class FareReportForm(forms.ModelForm):
    """US24 #71: a fare report from a signed-in rider; the owner and the
    status are set here, never taken from the request."""

    ride_at = NycDateTimeField(label="Ride date and time (New York time)")

    class Meta:
        model = FareReport
        fields = [
            "pickup_zone",
            "dropoff_zone",
            "ride_at",
            "taxi_fare",
            "rideshare_service",
            "rideshare_quote",
        ]
        labels = {
            "pickup_zone": "Pickup zone",
            "dropoff_zone": "Dropoff zone",
            "taxi_fare": "Taxi fare before tip ($)",
            "rideshare_service": "Rideshare service (optional)",
            "rideshare_quote": "Rideshare quote ($, optional)",
        }
        help_texts = {
            "taxi_fare": "What you paid in total, including tolls and surcharges, "
            "minus the tip. This matches the fare before tip the map shows.",
            "rideshare_quote": "The Uber or Lyft price you were quoted for the "
            "same trip at the same time.",
        }

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
        self.fields["rideshare_service"].choices = [
            ("", "None")
        ] + FareReport.SERVICE_CHOICES
        for name in ("taxi_fare", "rideshare_quote"):
            self.fields[name].widget.attrs.update({"min": "0.01", "step": "0.01"})

    def clean_taxi_fare(self):
        return _check_amount(
            self.cleaned_data["taxi_fare"], FARE_NOT_POSITIVE, FARE_TOO_HIGH
        )

    def clean_rideshare_quote(self):
        return _check_amount(
            self.cleaned_data["rideshare_quote"], QUOTE_NOT_POSITIVE, QUOTE_TOO_HIGH
        )

    def clean_ride_at(self):
        ride_at = self.cleaned_data["ride_at"]
        if ride_at > self.now:
            raise forms.ValidationError(RIDE_IN_FUTURE)
        if ride_at < self.now - MAX_AGE:
            raise forms.ValidationError(RIDE_TOO_OLD)
        return ride_at

    def clean(self):
        cleaned = super().clean()
        if reports_today(self.user, self.now) >= DAILY_LIMIT:
            raise forms.ValidationError(DAILY_LIMIT_REACHED)
        service = cleaned.get("rideshare_service")
        quote = cleaned.get("rideshare_quote")
        if quote is not None and not service:
            self.add_error("rideshare_service", QUOTE_NEEDS_SERVICE)
        if service and quote is None and "rideshare_quote" not in self.errors:
            self.add_error("rideshare_quote", SERVICE_NEEDS_QUOTE)
        return cleaned

    def save(self):
        report = super().save(commit=False)
        report.user = self.user
        report.status = review_status(
            report.pickup_zone_id,
            report.dropoff_zone_id,
            report.ride_at,
            report.taxi_fare,
        )
        report.save()
        return report
