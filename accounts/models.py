from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

DISPLAY_NAME_MAX_LENGTH = 30


class Profile(models.Model):
    """US30 #92: what other riders see of an account. Only the display name
    is shown to other riders, never the email. A user without a display
    name has no Profile row."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # deleting the account deletes the name
        related_name="profile",
    )
    display_name = models.CharField(max_length=DISPLAY_NAME_MAX_LENGTH)

    class Meta:
        constraints = [
            # Unique ignoring capitals, so "Alex" and "alex" can't both exist,
            # even when two people save them at the same moment.
            models.UniqueConstraint(
                Lower("display_name"), name="profile_display_name_unique_ci"
            ),
        ]

    def __str__(self):
        return self.display_name


class AccountAction(models.Model):
    """US46: an administrator's suspension or restoration of an account.
    US47 #121: also restrictions and their lifting. The latest restrict or
    lift row of an account decides whether it is restricted
    (accounts/restriction.py)."""

    SUSPEND = "suspend"
    RESTORE = "restore"
    RESTRICT = "restrict"
    LIFT = "lift"
    ACTION_CHOICES = [
        (SUSPEND, "Suspend"),
        (RESTORE, "Restore"),
        (RESTRICT, "Restrict"),
        (LIFT, "Lift restriction"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_actions",
    )
    action = models.CharField(max_length=8, choices=ACTION_CHOICES)
    reason = models.CharField(max_length=200)
    acted_by = models.CharField(max_length=150)
    acted_at = models.DateTimeField(auto_now_add=True)
    # US47: when a restriction stops applying (the start of the day after
    # its end date, New York time). Empty: no end date, or not a restriction.
    ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-acted_at", "-pk"]

    def __str__(self):
        return f"{self.get_action_display()} {self.user_id} by {self.acted_by}"
