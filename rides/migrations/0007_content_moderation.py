from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("rides", "0006_content_report")]

    operations = [
        migrations.AddField(
            model_name="ridemessage",
            name="hidden",
            field=models.BooleanField(default=False, db_default=False),
        ),
        migrations.AddField(
            model_name="contentreport",
            name="outcome",
            field=models.CharField(
                blank=True,
                default="",
                db_default="",
                choices=[
                    ("removed", "Content removed"),
                    ("no_action", "No action needed"),
                ],
                max_length=9,
            ),
        ),
        migrations.AddField(
            model_name="contentreport",
            name="closed_by",
            field=models.CharField(
                blank=True, default="", db_default="", max_length=150
            ),
        ),
        migrations.AddField(
            model_name="contentreport",
            name="closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="ridepost",
            name="status",
            field=models.CharField(
                choices=[
                    ("open", "Open"),
                    ("full", "Full"),
                    ("closed", "Closed"),
                    ("deleted", "Deleted"),
                    ("removed", "Removed by a moderator"),
                ],
                default="open",
                max_length=7,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="ridepost", name="ride_post_status_valid"
        ),
        migrations.AddConstraint(
            model_name="ridepost",
            constraint=models.CheckConstraint(
                condition=Q(
                    status__in=["open", "full", "closed", "deleted", "removed"]
                ),
                name="ride_post_status_valid",
            ),
        ),
    ]
