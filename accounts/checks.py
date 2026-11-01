from django.apps import apps
from django.conf import settings
from django.core import checks
from django.db import models


def cascade_errors(model_classes):
    """Errors for links to the user that would survive deleting the user.

    US12 #41: deleting an account must delete everything saved in it
    (saved routes in US13, plans in US17), so every ForeignKey or
    OneToOneField to the user needs on_delete=CASCADE.
    """
    errors = []
    for model in model_classes:
        if model._meta.app_label in ("admin", "auth"):
            continue  # Django's own tables
        for field in model._meta.get_fields():
            if (
                isinstance(field, (models.ForeignKey, models.OneToOneField))
                and field.related_model._meta.label == settings.AUTH_USER_MODEL
                and field.remote_field.on_delete is not models.CASCADE
            ):
                errors.append(
                    checks.Error(
                        f"{model.__name__}.{field.name} links to the user "
                        "without on_delete=models.CASCADE.",
                        hint="Deleting an account must delete everything saved "
                        "in it (US12 #41). Use on_delete=models.CASCADE.",
                        obj=field,
                        id="accounts.E001",
                    )
                )
    return errors


@checks.register(checks.Tags.models)
def user_data_cascades(app_configs, **kwargs):
    return cascade_errors(apps.get_models())
