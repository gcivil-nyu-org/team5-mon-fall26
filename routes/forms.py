from django import forms
from django.db import IntegrityError, transaction

from zones.models import Zone

from .models import SavedRoute

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
