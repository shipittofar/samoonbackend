# Generated manually for ExtraGroup Phase 1

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
        ("menu", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExtraGroup",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                (
                    "selection_type",
                    models.CharField(
                        choices=[("single", "Single"), ("multiple", "Multiple")],
                        default="multiple",
                        max_length=10,
                    ),
                ),
                ("required", models.BooleanField(default=False)),
                ("min_selection", models.PositiveIntegerField(default=0)),
                ("max_selection", models.PositiveIntegerField(default=1)),
                ("order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="extra_groups",
                        to="tenants.branch",
                    ),
                ),
            ],
            options={
                "db_table": "menu_extra_group",
                "ordering": ["order"],
            },
        ),
    ]
