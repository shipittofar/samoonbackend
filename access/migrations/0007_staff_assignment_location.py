import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0006_staff_assignment_additive_fields"),
        ("tenants", "0005_extend_owner"),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffAssignmentLocation",
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
                    "assignment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="locations",
                        to="access.staffassignment",
                    ),
                ),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="staff_assignment_locations",
                        to="tenants.branch",
                    ),
                ),
            ],
            options={
                "db_table": "staff_assignment_location",
                "indexes": [
                    models.Index(fields=["branch"], name="staff_assig_branch__f4a1de_idx")
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("assignment", "branch"),
                        name="unique_assignment_branch_location",
                    )
                ],
            },
        ),
    ]
