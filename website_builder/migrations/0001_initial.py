import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tenants", "0002_business_types_refactor"),
    ]

    operations = [
        migrations.CreateModel(
            name="WebsiteLayout",
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
                ("layout_data", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Draft"), ("published", "Published")],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("last_saved_at", models.DateTimeField(blank=True, null=True)),
                ("last_published_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="website_layout",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "website_layout",
            },
        ),
        migrations.CreateModel(
            name="BranchWebsiteOverride",
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
                ("override_data", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="website_overrides",
                        to="tenants.branch",
                    ),
                ),
                (
                    "website_layout",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="branch_overrides",
                        to="website_builder.websitelayout",
                    ),
                ),
            ],
            options={
                "db_table": "branch_website_override",
            },
        ),
        migrations.AddConstraint(
            model_name="branchwebsiteoverride",
            constraint=models.UniqueConstraint(
                fields=("website_layout", "branch"),
                name="unique_branch_website_override",
            ),
        ),
    ]
