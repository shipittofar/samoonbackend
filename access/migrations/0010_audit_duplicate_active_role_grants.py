import logging
import os

from django.db import migrations
from django.db.models import Count

logger = logging.getLogger(__name__)

NON_TERMINAL_STATUSES = ("active", "future")


def _in_ci() -> bool:
    return os.environ.get("CI", "").lower() in ("true", "1", "yes")


def audit_duplicate_active_role_grants(apps, schema_editor):
    StaffAssignment = apps.get_model("access", "StaffAssignment")

    duplicate_groups = (
        StaffAssignment.objects.filter(status__in=NON_TERMINAL_STATUSES)
        .values("membership_id", "role_id")
        .annotate(grant_count=Count("id"))
        .filter(grant_count__gt=1)
        .order_by("membership_id", "role_id")
    )

    violations = list(duplicate_groups)
    if not violations:
        return

    details = [
        (
            f"membership_id={row['membership_id']} "
            f"role_id={row['role_id']} "
            f"count={row['grant_count']}"
        )
        for row in violations
    ]
    message = (
        "Duplicate non-terminal StaffAssignment grants detected "
        f"({len(violations)} membership/role group(s)): " + "; ".join(details)
    )

    if _in_ci():
        raise RuntimeError(message)

    logger.warning(message)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0009_drop_legacy_assignment_uniqueness"),
    ]

    operations = [
        migrations.RunPython(audit_duplicate_active_role_grants, noop_reverse),
    ]
