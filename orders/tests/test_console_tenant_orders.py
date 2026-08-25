"""API tests for GET /api/orders/console-orders/tenants/{tenant_id}/branches/."""
import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from orders.models import Order, OrderStatus, OrderType, PaymentMethod
from tenants.models import Branch, Owner, Tenant


TENANT_ORDERS_URL = "/api/orders/console-orders/tenants/{tenant_id}/branches/"
BRANCH_ORDERS_URL = (
    "/api/orders/console-orders/tenants/{tenant_id}/branches/{branch_id}/"
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
    )
    return user, tenant


def make_branch(tenant, **kwargs):
    defaults = {
        "name": f"Branch {uuid.uuid4().hex[:6]}",
        "pickup_enabled": True,
    }
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


class ConsoleTenantOrdersListTests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant_with_owner()
        self.branch_a = make_branch(self.tenant, name="Branch A")
        self.branch_b = make_branch(self.tenant, name="Branch B")
        self.order_a = make_order(self.branch_a, order_number="ORD-SEARCH-ALPHA-001")
        self.order_b = make_order(
            self.branch_b,
            order_number="ORD-BETA-002",
            status=OrderStatus.CONFIRMED,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.url = TENANT_ORDERS_URL.format(tenant_id=self.tenant.id)

    def test_owner_receives_orders_from_all_tenant_branches(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        results = response.data["results"]
        order_ids = {row["id"] for row in results}
        self.assertEqual(
            order_ids,
            {str(self.order_a.id), str(self.order_b.id)},
        )

    def test_branch_filter_returns_only_matching_branch_orders(self):
        response = self.client.get(self.url, {"branch_id": str(self.branch_a.id)})

        self.assertEqual(response.status_code, 200, response.data)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(self.order_a.id))
        self.assertEqual(results[0]["branch_id"], str(self.branch_a.id))

    def test_status_filter_returns_only_matching_statuses(self):
        response = self.client.get(self.url, {"status": OrderStatus.CONFIRMED})

        self.assertEqual(response.status_code, 200, response.data)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(self.order_b.id))
        self.assertEqual(results[0]["status"], OrderStatus.CONFIRMED)

    def test_search_filter_matches_order_number(self):
        response = self.client.get(self.url, {"search": "SEARCH-ALPHA"})

        self.assertEqual(response.status_code, 200, response.data)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(self.order_a.id))

    def test_search_filter_matches_customer_email(self):
        customer = make_user(email="findme@example.com")
        order = make_order(self.branch_a, customer=customer, order_number="ORD-CUSTOM-003")

        response = self.client.get(self.url, {"search": "findme@example.com"})

        self.assertEqual(response.status_code, 200, response.data)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(order.id))

    def test_tenant_isolation(self):
        other_owner, other_tenant = make_tenant_with_owner()
        other_branch = make_branch(other_tenant)
        other_order = make_order(other_branch)

        response = self.client.get(TENANT_ORDERS_URL.format(tenant_id=other_tenant.id))

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["error"]["code"], "not_tenant_owner")

        self.client.force_authenticate(user=other_owner)
        response = self.client.get(TENANT_ORDERS_URL.format(tenant_id=other_tenant.id))
        self.assertEqual(response.status_code, 200, response.data)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(other_order.id))

    def test_unauthorized_non_owner_receives_forbidden(self):
        outsider = make_user()
        self.client.force_authenticate(user=outsider)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["error"]["code"], "not_tenant_owner")

    def test_empty_tenant_returns_empty_paginated_result(self):
        empty_owner, empty_tenant = make_tenant_with_owner()
        self.client.force_authenticate(user=empty_owner)

        response = self.client.get(TENANT_ORDERS_URL.format(tenant_id=empty_tenant.id))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_pagination_matches_branch_endpoint_shape(self):
        for index in range(3):
            make_order(self.branch_a, order_number=f"ORD-PAGE-{index:03d}")

        tenant_response = self.client.get(self.url, {"page": 1, "page_size": 2})
        branch_response = self.client.get(
            BRANCH_ORDERS_URL.format(
                tenant_id=self.tenant.id,
                branch_id=self.branch_a.id,
            ),
            {"page": 1, "page_size": 2},
        )

        self.assertEqual(tenant_response.status_code, 200, tenant_response.data)
        self.assertEqual(branch_response.status_code, 200, branch_response.data)
        self.assertIn("count", tenant_response.data)
        self.assertIn("results", tenant_response.data)
        self.assertIn("next", tenant_response.data)
        self.assertIn("previous", tenant_response.data)
        self.assertEqual(len(tenant_response.data["results"]), 2)
        self.assertEqual(set(tenant_response.data.keys()), set(branch_response.data.keys()))

    def test_unknown_tenant_returns_not_found(self):
        response = self.client.get(
            TENANT_ORDERS_URL.format(tenant_id=uuid.uuid4())
        )

        self.assertEqual(response.status_code, 404, response.data)
        self.assertEqual(response.data["error"]["code"], "tenant_not_found")
