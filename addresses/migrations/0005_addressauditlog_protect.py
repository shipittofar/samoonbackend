from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("addresses", "0004_verify_existing_addresses"),
    ]

    operations = [
        migrations.AlterField(
            model_name="addressauditlog",
            name="address",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="audit_logs",
                to="addresses.address",
            ),
        ),
    ]
