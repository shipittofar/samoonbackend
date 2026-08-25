"""Tests for tenant activation lifecycle driven by branch count."""
import uuid

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Branch, BranchStatus, Owner, Tenant, TenantStatus
from tenants.services import BranchBusinessLogicLayer, TenantBusinessLogicLayer
from tenants.services.tenant_activation import lifecycle_branches_exist


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


def make_owner_user():
    user = make_user()
    owner = Owner.objects.create(user=user)
    return user, owner


def make_branch(tenant, **kwargs):
    defaults = {"name": f"Branch {uuid.uuid4().hex[:6]}"}
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


def lifecycle_branch_count(tenant) -> int:
    return Branch.objects.filter(
        tenant_id=tenant.id,
        status=BranchStatus.ACTIVE,
        is_active=True,
    ).count()


def assert_activation_invariant(test_case, tenant):
    tenant.refresh_from_db()
    branch_count = lifecycle_branch_count(tenant)
    if branch_count == 0:
        test_case.assertEqual(tenant.status, TenantStatus.INACTIVE)
    else:
        test_case.assertEqual(tenant.status, TenantStatus.ACTIVE)


class TenantActivationLifecycleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user, self.owner = make_owner_user()
        self.client.force_authenticate(user=self.user)

    def _create_tenant_via_api(self, path="/api/tenants/create/"):
        response = self.client.post(
            path,
            data={"name": f"Tenant {uuid.uuid4().hex[:6]}"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response

    def _create_branch_via_api(self, tenant_id, name=None):
        name = name or f"Branch {uuid.uuid4().hex[:6]}"
        response = self.client.post(
            f"/api/branches/console-branches/tenants/{tenant_id}/create/",
            data={"name": name, "type": "physical"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response

    def _delete_branch_via_api(self, tenant_id, branch_id):
        return self.client.delete(
            f"/api/tenants/{tenant_id}/branches/{branch_id}/delete/",
        )

    def test_create_tenant_without_branches_is_inactive(self):
        response = self._create_tenant_via_api()
        self.assertEqual(response.data["status"], TenantStatus.INACTIVE)

        tenant = Tenant.objects.get(id=response.data["id"])
        self.assertEqual(tenant.status, TenantStatus.INACTIVE)
        self.assertFalse(lifecycle_branches_exist(tenant.id))
        assert_activation_invariant(self, tenant)

    def test_provision_tenant_without_branches_is_inactive(self):
        response = self._create_tenant_via_api(path="/api/tenants/provision/")
        self.assertEqual(response.data["status"], TenantStatus.INACTIVE)

    def test_create_tenant_ignores_requested_active_status(self):
        response = self.client.post(
            "/api/tenants/create/",
            data={"name": f"Tenant {uuid.uuid4().hex[:6]}", "status": TenantStatus.ACTIVE},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], TenantStatus.INACTIVE)

    def test_first_branch_activates_tenant(self):
        create_response = self._create_tenant_via_api()
        tenant = Tenant.objects.get(id=create_response.data["id"])
        self.assertEqual(tenant.status, TenantStatus.INACTIVE)

        branch_response = self._create_branch_via_api(tenant.id)
        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.ACTIVE)
        assert_activation_invariant(self, tenant)

        detail = self.client.get(f"/api/tenants/{tenant.id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["status"], TenantStatus.ACTIVE)
        self.assertEqual(detail.data["id"], str(tenant.id))
        self.assertEqual(branch_response.data["name"], branch_response.data["name"])

    def test_additional_branch_keeps_tenant_active(self):
        create_response = self._create_tenant_via_api()
        tenant = Tenant.objects.get(id=create_response.data["id"])

        self._create_branch_via_api(tenant.id, name="First")
        self._create_branch_via_api(tenant.id, name="Second")

        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.ACTIVE)
        self.assertEqual(lifecycle_branch_count(tenant), 2)
        assert_activation_invariant(self, tenant)

    def test_delete_last_branch_deactivates_tenant(self):
        create_response = self._create_tenant_via_api()
        tenant = Tenant.objects.get(id=create_response.data["id"])
        branch_response = self._create_branch_via_api(tenant.id)
        branch_id = branch_response.data["id"]

        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.ACTIVE)

        delete_response = self._delete_branch_via_api(tenant.id, branch_id)
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.INACTIVE)
        assert_activation_invariant(self, tenant)

    def test_delete_one_of_two_branches_keeps_tenant_active(self):
        create_response = self._create_tenant_via_api()
        tenant = Tenant.objects.get(id=create_response.data["id"])

        first = self._create_branch_via_api(tenant.id, name="First")
        self._create_branch_via_api(tenant.id, name="Second")

        delete_response = self._delete_branch_via_api(tenant.id, first.data["id"])
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.ACTIVE)
        self.assertEqual(lifecycle_branch_count(tenant), 1)
        assert_activation_invariant(self, tenant)

    def test_delete_final_branch_via_console_route_deactivates_tenant(self):
        create_response = self._create_tenant_via_api()
        tenant = Tenant.objects.get(id=create_response.data["id"])
        branch_response = self._create_branch_via_api(tenant.id)
        branch_id = branch_response.data["id"]

        response = self.client.delete(
            f"/api/branches/console-branches/branches/{branch_id}/delete/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.INACTIVE)
        assert_activation_invariant(self, tenant)

    def test_bll_create_tenant_is_inactive(self):
        tenant = TenantBusinessLogicLayer.create_tenant(
            user=self.user,
            name=f"BLL Tenant {uuid.uuid4().hex[:6]}",
            status=TenantStatus.ACTIVE,
        )
        self.assertEqual(tenant.status, TenantStatus.INACTIVE)
        assert_activation_invariant(self, tenant)

    def test_soft_deleted_branches_do_not_count_toward_activation(self):
        tenant = TenantBusinessLogicLayer.create_tenant(
            user=self.user,
            name=f"Soft Delete Tenant {uuid.uuid4().hex[:6]}",
        )
        branch = BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=tenant.id,
            name="Only Branch",
        )
        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.ACTIVE)

        BranchBusinessLogicLayer.delete_branch(
            user=self.user,
            tenant_id=tenant.id,
            branch_id=branch.id,
        )
        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.INACTIVE)

        BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=tenant.id,
            name="Replacement Branch",
        )
        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.ACTIVE)
        assert_activation_invariant(self, tenant)

    def test_closed_status_is_preserved(self):
        tenant = TenantBusinessLogicLayer.create_tenant(
            user=self.user,
            name=f"Closed Tenant {uuid.uuid4().hex[:6]}",
        )
        tenant.status = TenantStatus.CLOSED
        tenant.save(update_fields=["status"])

        BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=tenant.id,
            name="Branch on closed tenant",
        )
        tenant.refresh_from_db()
        self.assertEqual(tenant.status, TenantStatus.CLOSED)
