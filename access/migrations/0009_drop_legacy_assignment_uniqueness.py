from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0008_backfill_assignment_locations"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="staffassignment",
            name="unique_membership_branch_assignment",
        ),
        migrations.RemoveConstraint(
            model_name="staffassignment",
            name="unique_membership_tenant_wide_assignment",
        ),
    ]
