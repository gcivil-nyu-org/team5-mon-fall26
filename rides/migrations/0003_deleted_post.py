from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("rides", "0002_ride_interest")]

    operations = [
        migrations.RemoveConstraint(model_name="ridepost", name="ride_post_status_valid"),
        migrations.AlterField(
            model_name="ridepost",
            name="status",
            field=models.CharField(
                max_length=7,
                default="open",
                choices=[
                    ("open", "Open"),
                    ("full", "Full"),
                    ("closed", "Closed"),
                    ("deleted", "Deleted"),
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="ridepost",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=["open", "full", "closed", "deleted"]),
                name="ride_post_status_valid",
            ),
        ),
    ]
