from django import forms
from django.db import IntegrityError, transaction

from zones.models import Zone

from .models import DAY_CHOICES, SavedRoute, TripPlan

NAME_TAKEN = "You already have a saved route with this name."


class RouteNameForm(forms.Form):
    name = forms.CharField(max_length=50)

    def __init__(self, user, *args, route=None, **kwargs):
        self.user = user
        self.route = route
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"]
        matches = SavedRoute.objects.filter(user=self.user, name=name)
        if self.route is not None:
            matches = matches.exclude(pk=self.route.pk)
        if matches.exists():
            raise forms.ValidationError(NAME_TAKEN)
        return name


class SavedRouteForm(RouteNameForm):
    pickup_zone = forms.ModelChoiceField(queryset=Zone.objects.all())
    dropoff_zone = forms.ModelChoiceField(queryset=Zone.objects.all())

    def save(self):
        try:
            with transaction.atomic():
                return SavedRoute.objects.create(user=self.user, **self.cleaned_data)
        except IntegrityError:
            # A second request may have saved the same name after validation.
            if not SavedRoute.objects.filter(
                user=self.user, name=self.cleaned_data["name"]
            ).exists():
                raise
            self.add_error("name", NAME_TAKEN)
            return None


PLAN_NAME_TAKEN = "You already have a saved plan with this name."
QUARTER_HOUR = "Choose a time in 15-minute steps (for example 08:15)."


class PlanTimeForm(forms.Form):
    """Day and time of a plan. "Arrive by" times must be on a quarter hour,
    like /api/routes/leave-by; "Cheapest" start times may be any minute,
    because a plan made with "Now" keeps the exact time it was made."""

    day_of_week = forms.TypedChoiceField(choices=DAY_CHOICES, coerce=int, label="Day")
    time = forms.TimeField(input_formats=["%H:%M"], label="Time")

    def plan_mode(self):
        return self.mode

    def __init__(self, *args, mode=None, **kwargs):
        self.mode = mode
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        time = cleaned.get("time")
        if time is not None:
            if self.plan_mode() == TripPlan.ARRIVE_BY and time.minute % 15:
                self.add_error("time", QUARTER_HOUR)
            cleaned["time"] = time.replace(second=0, microsecond=0)
        return cleaned


class TripPlanForm(PlanTimeForm):
    """Everything needed to save a plan from the map (US17 #46)."""

    name = forms.CharField(max_length=50)
    pickup_zone = forms.ModelChoiceField(queryset=Zone.objects.all())
    dropoff_zone = forms.ModelChoiceField(queryset=Zone.objects.all())
    mode = forms.ChoiceField(choices=TripPlan.MODE_CHOICES)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def plan_mode(self):
        return self.cleaned_data.get("mode")

    def clean_name(self):
        name = self.cleaned_data["name"]
        if TripPlan.objects.filter(user=self.user, name=name).exists():
            raise forms.ValidationError(PLAN_NAME_TAKEN)
        return name

    def save(self):
        try:
            with transaction.atomic():
                return TripPlan.objects.create(user=self.user, **self.cleaned_data)
        except IntegrityError:
            # A second request may have saved the same name after validation.
            if not TripPlan.objects.filter(
                user=self.user, name=self.cleaned_data["name"]
            ).exists():
                raise
            self.add_error("name", PLAN_NAME_TAKEN)
            return None
