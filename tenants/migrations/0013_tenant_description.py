from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0012_tenant_hero_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="description",
            field=models.TextField(blank=True),
        ),
    ]
