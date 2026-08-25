"""Tests for RBAC seed data and migration."""
import uuid

from django.test import TestCase

from access.constants.rbac_seed import PERMISSIONS, ROLE_PERMISSIONS, ROLES
from access.models import Permission, Role, RolePermission


class RbacSeedTests(TestCase):
    def test_seed_constants_integrity(self):
        self.assertEqual(len(ROLES), 8)
        self.assertEqual(set(ROLE_PERMISSIONS), {role["slug"] for role in ROLES})
        self.assertNotIn("dashboard:access", {slug for _, _, slug, _ in PERMISSIONS})

    def test_migration_seeded_roles_and_permissions(self):
        self.assertEqual(Role.objects.filter(system_role=True).count(), 8)
        self.assertGreater(Permission.objects.count(), 0)
        owner_role = Role.objects.get(slug="owner")
        owner_perm_count = RolePermission.objects.filter(role=owner_role).count()
        self.assertGreater(owner_perm_count, 0)
        self.assertEqual(
            owner_perm_count,
            len(ROLE_PERMISSIONS["owner"]),
        )
