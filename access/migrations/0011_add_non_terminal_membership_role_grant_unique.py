from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0010_audit_duplicate_active_role_grants"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="staffassignment",
            constraint=models.UniqueConstraint(
                fields=("membership", "role"),
                condition=models.Q(status__in=("active", "future")),
                name="unique_non_terminal_membership_role_grant",
            ),
        ),
        migrations.AddConstraint(
            model_name="staffassignment",
            constraint=models.CheckConstraint(
                condition=models.Q(all_locations=False) | models.Q(branch__isnull=True),
                name="all_locations_implies_null_branch_mirror",
            ),
        ),
    ]
