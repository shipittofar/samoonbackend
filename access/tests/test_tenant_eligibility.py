"""Wave 1 — centralized tenant RBAC eligibility."""
import uuid

from django.test import TestCase

from access.constants.tenant_eligibility import is_tenant_rbac_eligible
from access.services.rbac_bll import rbac_bll
from accounts.models import User
from tenants.models import Owner, Tenant, TenantStatus


def make_user():
    user = User(
        id=uuid.uuid4(),
        phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
        email=f"{uuid.uuid4().hex}@example.com",
        first_name="Test",
        last_name="User",
    )
    user.set_password("testpass123")
    user.save()
    return user


def make_tenant(**kwargs):
    user = make_user()
    owner = Owner.objects.create(user=user)
    defaults = {
        "owner": owner,
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": TenantStatus.ACTIVE,
        "is_active": True,
    }
    defaults.update(kwargs)
    return Tenant.objects.create(**defaults), user, owner


class TenantEligibilityTests(TestCase):
    def test_active_tenant_is_eligible(self):
        tenant, _, _ = make_tenant()
        self.assertTrue(is_tenant_rbac_eligible(tenant))
        self.assertTrue(rbac_bll.is_tenant_rbac_eligible(tenant))

    def test_inactive_flag_denies_rbac(self):
        tenant, _, _ = make_tenant(is_active=False)
        self.assertFalse(is_tenant_rbac_eligible(tenant))

    def test_closed_status_denies_rbac(self):
        tenant, _, _ = make_tenant(status=TenantStatus.CLOSED)
        self.assertFalse(is_tenant_rbac_eligible(tenant))

    def test_inactive_status_denies_rbac(self):
        tenant, _, _ = make_tenant(status=TenantStatus.INACTIVE)
        self.assertFalse(is_tenant_rbac_eligible(tenant))

    def test_ineligible_tenant_returns_no_permissions_for_owner(self):
        tenant, owner_user, _ = make_tenant(status=TenantStatus.CLOSED)
        permissions = rbac_bll.get_effective_permissions(user=owner_user, tenant=tenant)
        self.assertEqual(permissions, [])
