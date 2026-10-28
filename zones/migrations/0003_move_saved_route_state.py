from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("zones", "0002_saved_route")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[migrations.DeleteModel(name="SavedRoute")],
        )
    ]
