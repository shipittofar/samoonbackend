"""Tests for permission denial behavior in tenant authorization."""
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import Role, StaffMembership, StaffMembershipStatus
from access.services.assignment_bll import assignment_bll
from accounts.models import User
from tenants.models import Owner, Tenant, TenantStatus


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
    tenant = Tenant.objects.create(status=TenantStatus.ACTIVE, 
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
    )
    return user, tenant


class RequirePermissionDenialTests(TestCase):
    def test_permission_denial_returns_403_not_500(self):
        owner_user, tenant = make_tenant_with_owner()
        other_user = make_user()
        waiter_role, _ = Role.objects.get_or_create(
            slug="waiter",
            defaults={"name": "Waiter", "system_role": True},
        )
        membership = StaffMembership.objects.create(
            user=other_user,
            tenant=tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        assignment_bll.create_assignment(
            membership_id=membership.id,
            role_id=waiter_role.id,
            all_locations=True,
        )

        client = APIClient()
        client.force_authenticate(user=other_user)
        response = client.put(
            f"/api/tenants/{tenant.id}/website/layout/",
            {"sections": []},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "permission_denied")
        # Saving the website layout (PUT) needs settings.edit; GET needs settings.view.
        self.assertIn("settings.edit", response.data["error"]["message"])
