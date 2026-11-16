"""US37 #99: remember when a post's owner saw each interested rider."""

from django.db import migrations, models
from django.db.models import F


def mark_existing_seen(apps, schema_editor):
    # Interests from before this story are not "new": the owner has had the
    # post page to see them. Only interests shown from now on count.
    RideInterest = apps.get_model("rides", "RideInterest")
    RideInterest.objects.filter(owner_seen_at__isnull=True).update(
        owner_seen_at=F("created_at")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("rides", "0004_ride_message"),
    ]

    operations = [
        migrations.AddField(
            model_name="rideinterest",
            name="owner_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(mark_existing_seen, migrations.RunPython.noop),
    ]
