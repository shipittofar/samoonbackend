"""Regression tests for the Phase Z.5 orders-app bugfix pass.

Covers: order creation against real Order model fields (branch/id),
status updates gated by tenant ownership (current production contract),
and customer isolation for retrieve/list.
"""
import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import StaffMembership, StaffMembershipStatus
from access.tests.helpers import create_canonical_assignment, get_role
from accounts.models import User
from menu.models import MenuCategory, MenuItem
from orders.models import Order, OrderStatus, OrderType, PaymentMethod
from tenants.models import Branch, Owner, Tenant, TenantStatus


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


def make_tenant_with_owner(**kwargs):
    owner_user = make_user()
    owner = Owner.objects.create(user=owner_user)
    defaults = {
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "owner": owner,
        "status": TenantStatus.ACTIVE,
        "is_active": True,
    }
    defaults.update(kwargs)
    tenant = Tenant.objects.create(**defaults)
    return owner_user, tenant


def make_branch(tenant, **kwargs):
    defaults = {
        "name": f"Branch {uuid.uuid4().hex[:6]}",
        "pickup_enabled": True,
    }
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


def make_staff_membership(user, tenant, *, role_slug=None, all_locations=True, branch=None):
    membership = StaffMembership.objects.create(
        user=user,
        tenant=tenant,
        status=StaffMembershipStatus.ACTIVE,
    )
    if role_slug is not None:
        create_canonical_assignment(
            membership=membership,
            role=get_role(role_slug),
            all_locations=all_locations,
            branch=branch,
        )
    return membership


def make_menu_item(branch, **kwargs):
    category = MenuCategory.objects.create(branch=branch, name="Mains")
    defaults = {"name": "Burger", "price": Decimal("10.00")}
    defaults.update(kwargs)
    return MenuItem.objects.create(branch=branch, category=category, **defaults)


class OrderCreationTests(TestCase):
    def test_create_order_uses_real_model_fields(self):
        """Order.branch (not .tenant) and Order.id must work end-to-end."""
        _, tenant = make_tenant_with_owner(tax_percentage="10.00")
        branch = make_branch(tenant)
        item = make_menu_item(branch)
        customer = make_user()

        client = APIClient()
        client.force_authenticate(user=customer)
        response = client.post(
            "/api/orders/",
            {
                "branch_id": str(branch.id),
                "order_type": OrderType.PICKUP,
                "payment_method": PaymentMethod.CASH,
                "items": [{"menu_item_id": str(item.id), "quantity": 2}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["branch_id"], str(branch.id))
        self.assertEqual(response.data["tenant_id"], str(tenant.id))
        item_payload = response.data["items"][0]
        self.assertEqual(item_payload["menu_item_id"], str(item.id))
        self.assertNotIn("id", item_payload)

        order = Order.objects.get(pk=response.data["id"])
        self.assertEqual(order.branch_id, branch.id)
        self.assertEqual(order.customer_id, customer.id)
        self.assertEqual(str(order.total), "22.00")


class OrderStatusUpdateTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant)
        self.item = make_menu_item(self.branch)
        self.customer = make_user()
        self.order = Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            customer=self.customer,
            branch=self.branch,
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
            status=OrderStatus.PENDING,
        )

    def test_status_update_denied_without_ownership(self):
        """Staff membership alone is not enough — status update is owner-gated."""
        staffer = make_user()
        make_staff_membership(staffer, self.tenant, role_slug=None)

        client = APIClient()
        client.force_authenticate(user=staffer)
        response = client.patch(
            f"/api/orders/{self.order.id}/status/",
            {"status": OrderStatus.CONFIRMED},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_status_update_allowed_for_tenant_owner(self):
        client = APIClient()
        client.force_authenticate(user=self.owner_user)
        response = client.patch(
            f"/api/orders/{self.order.id}/status/",
            {"status": OrderStatus.CONFIRMED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["branch_id"], str(self.branch.id))
        self.assertEqual(response.data["tenant_id"], str(self.tenant.id))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CONFIRMED)

    def test_status_update_denied_for_other_tenants_owner(self):
        other_owner, _ = make_tenant_with_owner()

        client = APIClient()
        client.force_authenticate(user=other_owner)
        response = client.patch(
            f"/api/orders/{self.order.id}/status/",
            {"status": OrderStatus.CONFIRMED},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING)

    def test_status_update_denied_for_manager_assignment_without_ownership(self):
        """Manager StaffAssignment does not bypass tenant-owner gate."""
        other_branch = make_branch(self.tenant)
        staffer = make_user()
        make_staff_membership(
            staffer,
            self.tenant,
            role_slug="manager",
            all_locations=False,
            branch=other_branch,
        )

        client = APIClient()
        client.force_authenticate(user=staffer)
        response = client.patch(
            f"/api/orders/{self.order.id}/status/",
            {"status": OrderStatus.CONFIRMED},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_status_update_denied_for_manager_on_order_branch_without_ownership(self):
        staffer = make_user()
        make_staff_membership(
            staffer,
            self.tenant,
            role_slug="manager",
            all_locations=False,
            branch=self.branch,
        )

        client = APIClient()
        client.force_authenticate(user=staffer)
        response = client.patch(
            f"/api/orders/{self.order.id}/status/",
            {"status": OrderStatus.CONFIRMED},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_status_update_guest_order_with_null_customer(self):
        """Nullable customer FK must not break FOR UPDATE select_related."""
        guest_order = Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            customer=None,
            branch=self.branch,
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
            status=OrderStatus.PENDING,
        )

        client = APIClient()
        client.force_authenticate(user=self.owner_user)
        response = client.patch(
            f"/api/orders/{guest_order.id}/status/",
            {"status": OrderStatus.CONFIRMED},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["branch_id"], str(self.branch.id))
        self.assertEqual(response.data["tenant_id"], str(self.tenant.id))
        guest_order.refresh_from_db()
        self.assertEqual(guest_order.status, OrderStatus.CONFIRMED)


class DineInOrderStatusLifecycleTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant)
        self.order = Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            branch=self.branch,
            order_type=OrderType.DINE_IN,
            table_number=1,
            payment_method=PaymentMethod.CASH,
            status=OrderStatus.PENDING,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner_user)
        self.status_url = f"/api/orders/{self.order.id}/status/"

    def update_status(self, status):
        return self.client.patch(
            self.status_url,
            {"status": status},
            format="json",
        )

    def move_order_to_served(self):
        for status in (
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.READY,
            OrderStatus.SERVED,
        ):
            response = self.update_status(status)
            self.assertEqual(response.status_code, 200, response.data)

    def test_dine_in_order_progresses_to_served_and_stops(self):
        self.move_order_to_served()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.SERVED)
        self.assertEqual(
            list(self.order.status_history.values_list("status", flat=True)),
            [
                OrderStatus.SERVED,
                OrderStatus.READY,
                OrderStatus.PREPARING,
                OrderStatus.CONFIRMED,
            ],
        )

    def test_served_dine_in_order_cannot_transition_to_completed(self):
        self.move_order_to_served()

        response = self.update_status(OrderStatus.COMPLETED)

        self.assertEqual(response.status_code, 400, response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.SERVED)

    def test_dine_in_order_cannot_skip_served_for_completed(self):
        for status in (
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.READY,
        ):
            response = self.update_status(status)
            self.assertEqual(response.status_code, 200, response.data)

        response = self.update_status(OrderStatus.COMPLETED)

        self.assertEqual(response.status_code, 400, response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.READY)

    def test_served_dine_in_order_cannot_transition_to_closed(self):
        self.move_order_to_served()

        response = self.update_status("closed")

        self.assertEqual(response.status_code, 400, response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.SERVED)

    def test_delivery_and_pickup_terminal_paths_remain_unchanged(self):
        for order_type, next_status in (
            (OrderType.DELIVERY, OrderStatus.DELIVERED),
            (OrderType.PICKUP, OrderStatus.PICKED_UP),
        ):
            order = Order.objects.create(
                order_number=f"ORD-{uuid.uuid4().hex[:10]}",
                branch=self.branch,
                order_type=order_type,
                payment_method=PaymentMethod.CASH,
                status=OrderStatus.READY,
            )
            response = self.client.patch(
                f"/api/orders/{order.id}/status/",
                {"status": next_status},
                format="json",
            )

            self.assertEqual(response.status_code, 200, response.data)
            order.refresh_from_db()
            self.assertEqual(order.status, next_status)


class OrderCustomerIsolationTests(TestCase):
    def test_customer_cannot_view_another_customers_order(self):
        _, tenant = make_tenant_with_owner()
        branch = make_branch(tenant)
        owner_customer = make_user()
        other_customer = make_user()
        order = Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            customer=owner_customer,
            branch=branch,
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
        )

        client = APIClient()
        client.force_authenticate(user=other_customer)
        response = client.get(f"/api/orders/{order.id}/")
        self.assertEqual(response.status_code, 404)

    def test_order_list_only_returns_own_orders(self):
        _, tenant = make_tenant_with_owner()
        branch = make_branch(tenant)
        me = make_user()
        someone_else = make_user()
        Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            customer=me,
            branch=branch,
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
        )
        Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            customer=someone_else,
            branch=branch,
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
        )

        client = APIClient()
        client.force_authenticate(user=me)
        response = client.get("/api/orders/")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
