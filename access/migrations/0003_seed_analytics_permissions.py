# LEGACY: pre-Phase-1 inline seed data. Canonical RBAC definitions live in
# access/constants/rbac_seed.py (migration 0005). Do not extend this file.
import uuid

from django.db import migrations


PERMISSIONS = [
    ("analytics", "view", "analytics.view"),
    ("analytics", "export", "analytics.export"),
]

ROLE_PERMISSIONS = {
    "admin": {"analytics.view", "analytics.export"},
    "manager": {"analytics.view"},
    "marketing": {"analytics.view", "analytics.export"},
}


def seed_analytics_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")

    permission_objs = {}
    for resource, action, slug in PERMISSIONS:
        permission, _ = Permission.objects.get_or_create(
            slug=slug,
            defaults={
                "id": uuid.uuid4(),
                "resource": resource,
                "action": action,
            },
        )
        permission_objs[slug] = permission

    for role_slug, slugs in ROLE_PERMISSIONS.items():
        role = Role.objects.filter(slug=role_slug).first()
        if role is None:
            continue
        for slug in slugs:
            permission = permission_objs.get(slug)
            if permission is None:
                continue
            RolePermission.objects.get_or_create(role=role, permission=permission)


def unseed_analytics_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    RolePermission = apps.get_model("access", "RolePermission")

    slugs = [slug for _, _, slug in PERMISSIONS]
    RolePermission.objects.filter(permission__slug__in=slugs).delete()
    Permission.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(
            seed_analytics_permissions,
            reverse_code=unseed_analytics_permissions,
        ),
    ]
