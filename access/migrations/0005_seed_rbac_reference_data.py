from django.db import migrations

from access.constants.rbac_seed import PERMISSIONS, ROLE_PERMISSIONS, ROLES


def seed_rbac_reference_data(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")
    RolePermission = apps.get_model("access", "RolePermission")

    role_by_slug: dict[str, object] = {}
    for role_data in ROLES:
        role, _ = Role.objects.update_or_create(
            slug=role_data["slug"],
            defaults={
                "name": role_data["name"],
                "description": role_data["description"],
                "system_role": role_data["system_role"],
            },
        )
        role_by_slug[role.slug] = role

    permission_by_slug: dict[str, object] = {}
    for resource, action, slug, description in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            slug=slug,
            defaults={
                "resource": resource,
                "action": action,
                "description": description,
            },
        )
        permission_by_slug[slug] = permission

    for role_slug, permission_slugs in ROLE_PERMISSIONS.items():
        role = role_by_slug[role_slug]
        for perm_slug in permission_slugs:
            permission = permission_by_slug[perm_slug]
            RolePermission.objects.get_or_create(role=role, permission=permission)

    # Bust catalog caches so deploys pick up seeded reference data immediately.
    from access.constants.rbac_cache import bust_rbac_catalog_caches

    bust_rbac_catalog_caches()


def unseed_rbac_reference_data(apps, schema_editor):
    # Reverse only removes role-permission links created for seeded roles;
    # permissions/roles are left in place to avoid breaking FK references.
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")
    RolePermission = apps.get_model("access", "RolePermission")

    role_slugs = [role["slug"] for role in ROLES]
    perm_slugs = [slug for _, _, slug, _ in PERMISSIONS]

    RolePermission.objects.filter(
        role__slug__in=role_slugs,
        permission__slug__in=perm_slugs,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0004_seed_settings_permissions"),
    ]

    operations = [
        migrations.RunPython(
            seed_rbac_reference_data,
            reverse_code=unseed_rbac_reference_data,
        ),
    ]
