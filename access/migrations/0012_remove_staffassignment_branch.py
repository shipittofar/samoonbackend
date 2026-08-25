from django.db import migrations


def audit_canonical_assignment_scope(apps, schema_editor):
    from django.db.models import Count

    StaffAssignment = apps.get_model("access", "StaffAssignment")

    invalid_ids = list(
        StaffAssignment.objects.filter(all_locations=False)
        .annotate(location_count=Count("locations"))
        .filter(location_count=0)
        .values_list("id", flat=True)
    )
    if invalid_ids:
        raise RuntimeError(
            "Cannot remove StaffAssignment.branch until scoped assignments have "
            f"StaffAssignmentLocation rows. Run consolidate_legacy_assignments first. "
            f"Invalid assignment ids: {invalid_ids[:10]}"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0011_add_non_terminal_membership_role_grant_unique"),
    ]

    operations = [
        migrations.RunPython(audit_canonical_assignment_scope, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="staffassignment",
            name="all_locations_implies_null_branch_mirror",
        ),
        migrations.RemoveIndex(
            model_name="staffassignment",
            name="staff_assig_branch__a3e02a_idx",
        ),
        migrations.RemoveField(
            model_name="staffassignment",
            name="branch",
        ),
    ]
