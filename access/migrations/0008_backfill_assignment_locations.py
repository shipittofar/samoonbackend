from django.db import migrations


def backfill_assignment_locations(apps, schema_editor):
    StaffAssignment = apps.get_model("access", "StaffAssignment")
    StaffAssignmentLocation = apps.get_model("access", "StaffAssignmentLocation")

    for assignment in StaffAssignment.objects.all().iterator():
        if assignment.branch_id:
            StaffAssignmentLocation.objects.get_or_create(
                assignment_id=assignment.id,
                branch_id=assignment.branch_id,
            )
            if assignment.all_locations:
                assignment.all_locations = False
                assignment.save(update_fields=["all_locations"])
        elif not assignment.all_locations:
            assignment.all_locations = True
            assignment.save(update_fields=["all_locations"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0007_staff_assignment_location"),
    ]

    operations = [
        migrations.RunPython(backfill_assignment_locations, noop_reverse),
    ]
