from django.db import migrations

from access.constants.rbac_seed import ROLE_PERMISSIONS


def remove_manage_roles_from_owner(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    Permission = apps.get_model("access", "Permission")

    owner_role = Role.objects.filter(slug="owner").first()
    permission = Permission.objects.filter(slug="rbac.manage_roles").first()
    if owner_role is None or permission is None:
        return

    RolePermission.objects.filter(role=owner_role, permission=permission).delete()

    owner_slugs = ROLE_PERMISSIONS["owner"]
    for slug in owner_slugs:
        perm = Permission.objects.filter(slug=slug).first()
        if perm is None:
            continue
        RolePermission.objects.get_or_create(role=owner_role, permission=perm)


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0015_seed_rbac_manage_roles_permission"),
    ]

    operations = [
        migrations.RunPython(
            remove_manage_roles_from_owner,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
