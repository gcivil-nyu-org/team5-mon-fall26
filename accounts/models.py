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
