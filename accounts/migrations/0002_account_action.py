import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_profile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountAction",
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
                (
                    "action",
                    models.CharField(
                        choices=[("suspend", "Suspend"), ("restore", "Restore")],
                        max_length=7,
                    ),
                ),
                ("reason", models.CharField(max_length=200)),
                ("acted_by", models.CharField(max_length=150)),
                ("acted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="account_actions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-acted_at", "-pk"]},
        ),
    ]
