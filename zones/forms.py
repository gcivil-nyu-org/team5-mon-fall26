from django import forms
from django.db import IntegrityError, transaction

from .models import SavedRoute, Zone

NAME_TAKEN = "You already have a saved route with this name."


class SavedRouteForm(forms.Form):
    name = forms.CharField(max_length=50)
    pickup_zone = forms.ModelChoiceField(queryset=Zone.objects.all())
    dropoff_zone = forms.ModelChoiceField(queryset=Zone.objects.all())

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"]
        if SavedRoute.objects.filter(user=self.user, name=name).exists():
            raise forms.ValidationError(NAME_TAKEN)
        return name

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
