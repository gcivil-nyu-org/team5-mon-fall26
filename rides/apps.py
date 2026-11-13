from django.apps import AppConfig


class RidesConfig(AppConfig):
    """Epic 4: ride-sharing between riders. Other riders only ever see a
    rider's display name (US30 #92), never their email."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "rides"
