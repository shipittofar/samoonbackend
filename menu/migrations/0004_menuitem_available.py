from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0003_extra_group_fk_and_menuitemextragroup"),
    ]

    operations = [
        migrations.AddField(
            model_name="menuitem",
            name="available",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Ordering flag — unavailable items remain visible "
                    "but cannot be ordered."
                ),
            ),
        ),
    ]
