from django.db import migrations

from access.constants.rbac_seed import PERMISSIONS


def seed_rbac_manage_roles_permission(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")

    for resource, action, slug, description in PERMISSIONS:
        if slug != "rbac.manage_roles":
            continue
        Permission.objects.update_or_create(
            slug=slug,
            defaults={
                "resource": resource,
                "action": action,
                "description": description,
            },
        )

    from access.constants.rbac_cache import bust_rbac_catalog_caches

    bust_rbac_catalog_caches()


def unseed_rbac_manage_roles_permission(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    RolePermission = apps.get_model("access", "RolePermission")

    RolePermission.objects.filter(permission__slug="rbac.manage_roles").delete()
    Permission.objects.filter(slug="rbac.manage_roles").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0014_permission_override_and_audit"),
    ]

    operations = [
        migrations.RunPython(
            seed_rbac_manage_roles_permission,
            reverse_code=unseed_rbac_manage_roles_permission,
        ),
    ]
