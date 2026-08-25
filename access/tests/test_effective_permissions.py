"""Tests for get_effective_permissions — owner resolves via role, not bypass."""
import uuid

from django.test import TestCase

from access.constants.rbac_seed import ROLE_PERMISSIONS
from access.models import Role, RolePermission, StaffMembership, StaffMembershipStatus
from access.services.assignment_bll import assignment_bll
from access.services.rbac_bll import rbac_bll
from accounts.models import User
from tenants.models import Owner, Tenant


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


def make_tenant_with_owner():
    user = make_user()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return user, tenant


class EffectivePermissionsTests(TestCase):
    def test_owner_permissions_flow_through_owner_role(self):
        owner_user, tenant = make_tenant_with_owner()
        expected = sorted(ROLE_PERMISSIONS["owner"])

        effective = rbac_bll.get_effective_permissions(user=owner_user, tenant=tenant)
        self.assertEqual(effective, expected)

    def test_removing_owner_role_permissions_reduces_grants(self):
        owner_user, tenant = make_tenant_with_owner()
        owner_role = Role.objects.get(slug="owner")
        first_link = RolePermission.objects.filter(role=owner_role).first()
        removed_slug = first_link.permission.slug
        first_link.delete()

        effective = rbac_bll.get_effective_permissions(user=owner_user, tenant=tenant)
        self.assertNotIn(removed_slug, effective)

    def test_staff_receives_union_of_assignment_role_permissions(self):
        owner_user, tenant = make_tenant_with_owner()
        staff_user = make_user()
        waiter_role = Role.objects.get(slug="waiter")
        membership = StaffMembership.objects.create(
            user=staff_user,
            tenant=tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        assignment_bll.create_assignment(
            membership_id=membership.id,
            role_id=waiter_role.id,
            all_locations=True,
        )

        effective = rbac_bll.get_effective_permissions(user=staff_user, tenant=tenant)
        expected = sorted(ROLE_PERMISSIONS["waiter"])
        self.assertEqual(effective, expected)
