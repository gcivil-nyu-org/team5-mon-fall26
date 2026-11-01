from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """User accounts (Epic 2): sign up, sign in, manage account.

    Uses Django's built-in User model. The email address, lowercased, is
    stored as both username and email (see docs/decisions.md, US10 #39).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from . import checks  # noqa: F401  registers the system check
