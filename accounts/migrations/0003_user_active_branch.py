import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_initial"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="active_branch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="tenants.branch",
            ),
        ),
    ]
