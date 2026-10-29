import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("zones", "0003_move_saved_route_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="SavedRoute",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("name", models.CharField(max_length=50)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        (
                            "pickup_zone",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="saved_routes_from",
                                to="zones.zone",
                            ),
                        ),
                        (
                            "dropoff_zone",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="saved_routes_to",
                                to="zones.zone",
                            ),
                        ),
                        (
                            "user",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="saved_routes",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "db_table": "zones_savedroute",
                        "ordering": ["-created_at", "-pk"],
                        "constraints": [
                            models.UniqueConstraint(
                                fields=("user", "name"),
                                name="unique_user_route_name",
                            )
                        ],
                    },
                )
            ],
        )
    ]
