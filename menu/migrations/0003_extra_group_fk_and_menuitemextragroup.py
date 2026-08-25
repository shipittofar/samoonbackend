# Generated manually for ExtraGroup Phase 2 + MenuItemExtraGroup

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0002_extragroup"),
    ]

    operations = [
        migrations.AddField(
            model_name="extra",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="extra",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="extra",
            name="order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="extra",
            name="group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="extras",
                to="menu.extragroup",
            ),
        ),
        migrations.AlterModelOptions(
            name="extra",
            options={"ordering": ["order"]},
        ),
        migrations.CreateModel(
            name="MenuItemExtraGroup",
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
                    "extra_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="item_links",
                        to="menu.extragroup",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="item_extra_groups",
                        to="menu.menuitem",
                    ),
                ),
            ],
            options={
                "db_table": "menu_item_extra_group",
                "unique_together": {("item", "extra_group")},
            },
        ),
    ]
