"""HTTP tests for tenant+branch scoped pending order counts."""
import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import StaffMembership, StaffMembershipStatus
from access.tests.helpers import create_canonical_assignment, get_role
from accounts.models import User
from orders.models import Order, OrderStatus, OrderType, PaymentMethod
from tenants.models import Branch, Owner, Tenant, TenantStatus


PENDING_COUNT_URL = (
    "/api/orders/console-orders/tenants/{tenant_id}/branches/{branch_id}/pending-count/"
)


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
        status=TenantStatus.ACTIVE,
        is_active=True,
    )
    return user, tenant


def make_branch(tenant, **kwargs):
    defaults = {"name": f"Branch {uuid.uuid4().hex[:6]}", "pickup_enabled": True}
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


def make_order(branch, **kwargs):
    defaults = {
        "order_number": f"ORD-{uuid.uuid4().hex[:10]}",
        "branch": branch,
        "order_type": OrderType.PICKUP,
        "payment_method": PaymentMethod.CASH,
        "status": OrderStatus.PENDING,
        "total": Decimal("25.00"),
    }
    defaults.update(kwargs)
    return Order.objects.create(**defaults)


def assign_role(user, tenant, role_slug, *, branch=None, all_locations=False):
    membership = StaffMembership.objects.create(
        user=user,
        tenant=tenant,
        status=StaffMembershipStatus.ACTIVE,
    )
    create_canonical_assignment(
        membership=membership,
        role=get_role(role_slug),
        branch=branch,
        all_locations=all_locations,
    )
    return membership


class ConsolePendingOrderCountTests(TestCase):
    def setUp(self):
        self.owner_a, self.tenant_a = make_tenant_with_owner()
        self.branch_a = make_branch(self.tenant_a, name="A")
        self.branch_b = make_branch(self.tenant_a, name="B")
        self.owner_b, self.tenant_b = make_tenant_with_owner()
        self.branch_tenant_b = make_branch(self.tenant_b, name="TB-A")

        for _ in range(3):
            make_order(self.branch_a, status=OrderStatus.PENDING)
        make_order(self.branch_a, status=OrderStatus.CONFIRMED)
        make_order(self.branch_a, status=OrderStatus.CANCELLED)
        make_order(self.branch_a, status=OrderStatus.COMPLETED)

        for _ in range(7):
            make_order(self.branch_b, status=OrderStatus.PENDING)
        make_order(self.branch_b, status=OrderStatus.PREPARING)

        for _ in range(9):
            make_order(self.branch_tenant_b, status=OrderStatus.PENDING)

        self.client = APIClient()

    def url(self, tenant, branch):
        return PENDING_COUNT_URL.format(tenant_id=tenant.id, branch_id=branch.id)

    def test_owner_count_is_scoped_to_branch_a(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(self.url(self.tenant_a, self.branch_a))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 3})

    def test_owner_count_is_scoped_to_branch_b(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(self.url(self.tenant_a, self.branch_b))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 7})

    def test_other_tenant_owner_count(self):
        self.client.force_authenticate(user=self.owner_b)
        response = self.client.get(self.url(self.tenant_b, self.branch_tenant_b))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 9})

    def test_zero_pending(self):
        empty_owner, empty_tenant = make_tenant_with_owner()
        empty_branch = make_branch(empty_tenant)
        make_order(empty_branch, status=OrderStatus.CONFIRMED)
        self.client.force_authenticate(user=empty_owner)
        response = self.client.get(self.url(empty_tenant, empty_branch))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 0})

    def test_owner_cannot_query_other_tenant(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(self.url(self.tenant_b, self.branch_tenant_b))
        self.assertEqual(response.status_code, 403, response.data)

    def test_mismatched_tenant_and_branch_is_not_found(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(self.url(self.tenant_a, self.branch_tenant_b))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["error"]["code"], "branch_not_found")

    def test_unauthenticated(self):
        response = self.client.get(self.url(self.tenant_a, self.branch_a))
        self.assertEqual(response.status_code, 401)

    def test_staff_with_orders_view_on_branch_a_only(self):
        waiter = make_user()
        assign_role(waiter, self.tenant_a, "waiter", branch=self.branch_a)
        self.client.force_authenticate(user=waiter)

        allowed = self.client.get(self.url(self.tenant_a, self.branch_a))
        self.assertEqual(allowed.status_code, 200, allowed.data)
        self.assertEqual(allowed.data, {"count": 3})

        denied = self.client.get(self.url(self.tenant_a, self.branch_b))
        self.assertEqual(denied.status_code, 403, denied.data)

    def test_support_without_orders_view_is_denied(self):
        support = make_user()
        assign_role(support, self.tenant_a, "support", branch=self.branch_a)
        self.client.force_authenticate(user=support)
        response = self.client.get(self.url(self.tenant_a, self.branch_a))
        self.assertEqual(response.status_code, 403, response.data)

    def test_query_params_cannot_override_scope(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(
            self.url(self.tenant_a, self.branch_a),
            {
                "tenant_id": str(self.tenant_b.id),
                "branch_id": str(self.branch_tenant_b.id),
                "admin": "true",
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 3})
