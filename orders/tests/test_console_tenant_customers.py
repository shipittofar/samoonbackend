"""API tests for GET /api/orders/console-orders/tenants/{tenant_id}/customers/."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from orders.models import Order, OrderStatus, OrderType, PaymentMethod
from reservations.models import Reservation, ReservationStatus
from tenants.models import Branch, Owner, Tenant


CUSTOMERS_URL = "/api/orders/console-orders/tenants/{tenant_id}/customers/"


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
        "reservations_enabled": True,
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


def make_reservation(branch, **kwargs):
    defaults = {
        "branch": branch,
        "guest_name": "Guest",
        "guest_phone": "+15550001111",
        "party_size": 2,
        "reserved_at": timezone.now() + timedelta(hours=2),
        "status": ReservationStatus.PENDING,
    }
    defaults.update(kwargs)
    return Reservation.objects.create(**defaults)


class ConsoleTenantCustomersListTests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant_with_owner()
        self.branch_a = make_branch(self.tenant, name="Branch A")
        self.branch_b = make_branch(self.tenant, name="Branch B")
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.url = CUSTOMERS_URL.format(tenant_id=self.tenant.id)

    def _ids(self, response):
        return {row["id"] for row in response.data["results"]}

    def test_owner_retrieves_tenant_customers_from_orders(self):
        customer = make_user(first_name="Ada")
        make_order(self.branch_a, customer=customer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(customer.id)})
        row = response.data["results"][0]
        self.assertEqual(row["first_name"], "Ada")
        self.assertEqual(row["orders_count"], 1)
        self.assertEqual(row["reservations_count"], 0)
        self.assertIsNotNone(row["last_activity_at"])

    def test_customer_from_another_tenant_is_not_returned(self):
        customer = make_user()
        make_order(self.branch_a, customer=customer)

        _, other_tenant = make_tenant_with_owner()
        other_branch = make_branch(other_tenant)
        outsider = make_user(first_name="Other")
        make_order(other_branch, customer=outsider)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(customer.id)})

    def test_branch_filter_returns_only_matching_branch_customers(self):
        customer_a = make_user(first_name="Alpha")
        customer_b = make_user(first_name="Beta")
        make_order(self.branch_a, customer=customer_a)
        make_order(self.branch_b, customer=customer_b)

        response = self.client.get(self.url, {"branch_id": str(self.branch_a.id)})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(customer_a.id)})

    def test_customer_from_another_branch_not_returned_when_filtered(self):
        customer_b = make_user()
        make_order(self.branch_b, customer=customer_b)

        response = self.client.get(self.url, {"branch_id": str(self.branch_a.id)})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_branch_from_another_tenant_returns_not_found(self):
        _, other_tenant = make_tenant_with_owner()
        foreign_branch = make_branch(other_tenant)

        response = self.client.get(self.url, {"branch_id": str(foreign_branch.id)})

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["error"]["code"], "branch_not_found")

    def test_customer_with_multiple_orders_appears_once(self):
        customer = make_user()
        make_order(self.branch_a, customer=customer)
        make_order(self.branch_a, customer=customer)
        make_order(self.branch_b, customer=customer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], str(customer.id))
        self.assertEqual(response.data["results"][0]["orders_count"], 3)

    def test_reservation_customer_appears(self):
        customer = make_user(first_name="Reserved")
        make_reservation(self.branch_a, customer=customer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(customer.id)})
        self.assertEqual(response.data["results"][0]["orders_count"], 0)
        self.assertEqual(response.data["results"][0]["reservations_count"], 1)

    def test_customer_with_multiple_reservations_appears_once(self):
        customer = make_user()
        make_reservation(self.branch_a, customer=customer)
        make_reservation(self.branch_b, customer=customer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["reservations_count"], 2)

    def test_customer_with_order_and_reservation_appears_once(self):
        customer = make_user()
        make_order(self.branch_a, customer=customer)
        make_reservation(self.branch_b, customer=customer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["results"]), 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], str(customer.id))
        self.assertEqual(row["orders_count"], 1)
        self.assertEqual(row["reservations_count"], 1)

    def test_guest_order_does_not_create_customer(self):
        make_order(self.branch_a, customer=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_guest_reservation_does_not_create_customer(self):
        make_reservation(self.branch_a, customer=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_platform_superuser_is_not_returned(self):
        admin = make_user(is_superuser=True, first_name="Admin")
        make_order(self.branch_a, customer=admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"], [])

    def test_search_by_email(self):
        matching = make_user(email="findme@example.com")
        other = make_user(email="other@example.com")
        make_order(self.branch_a, customer=matching)
        make_order(self.branch_a, customer=other)

        response = self.client.get(self.url, {"search": "findme@example.com"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(matching.id)})

    def test_search_by_phone(self):
        matching = make_user(phone_number="+49123456789")
        other = make_user()
        make_order(self.branch_a, customer=matching)
        make_order(self.branch_a, customer=other)

        response = self.client.get(self.url, {"search": "123456789"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(matching.id)})

    def test_search_by_first_name(self):
        matching = make_user(first_name="Zelda")
        other = make_user(first_name="Link")
        make_order(self.branch_a, customer=matching)
        make_order(self.branch_a, customer=other)

        response = self.client.get(self.url, {"search": "Zelda"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(matching.id)})

    def test_search_by_last_name(self):
        matching = make_user(last_name="Hyrule")
        other = make_user(last_name="Kokiri")
        make_order(self.branch_a, customer=matching)
        make_order(self.branch_a, customer=other)

        response = self.client.get(self.url, {"search": "Hyrule"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(matching.id)})

    def test_search_by_full_name(self):
        matching = make_user(first_name="Jane", last_name="Doe")
        make_order(self.branch_a, customer=matching)

        response = self.client.get(self.url, {"search": "Jane Doe"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(matching.id)})

    def test_pagination_matches_console_orders_shape(self):
        for index in range(3):
            customer = make_user(first_name=f"Page{index}")
            make_order(self.branch_a, customer=customer)

        response = self.client.get(self.url, {"page": 1, "page_size": 2})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIn("next", response.data)
        self.assertIn("previous", response.data)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_unauthorized_non_owner_receives_forbidden(self):
        outsider = make_user()
        self.client.force_authenticate(user=outsider)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["error"]["code"], "not_tenant_owner")

    def test_cannot_access_another_tenant_customers(self):
        other_owner, other_tenant = make_tenant_with_owner()
        other_branch = make_branch(other_tenant)
        other_customer = make_user()
        make_order(other_branch, customer=other_customer)

        response = self.client.get(CUSTOMERS_URL.format(tenant_id=other_tenant.id))

        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["error"]["code"], "not_tenant_owner")

        self.client.force_authenticate(user=other_owner)
        response = self.client.get(CUSTOMERS_URL.format(tenant_id=other_tenant.id))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._ids(response), {str(other_customer.id)})

    def test_empty_tenant_returns_empty_paginated_result(self):
        empty_owner, empty_tenant = make_tenant_with_owner()
        self.client.force_authenticate(user=empty_owner)

        response = self.client.get(CUSTOMERS_URL.format(tenant_id=empty_tenant.id))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])
        self.assertIn("next", response.data)
        self.assertIn("previous", response.data)

    def test_unknown_tenant_returns_not_found(self):
        response = self.client.get(CUSTOMERS_URL.format(tenant_id=uuid.uuid4()))

        self.assertEqual(response.status_code, 404, response.data)
        self.assertEqual(response.data["error"]["code"], "tenant_not_found")

    def test_response_does_not_expose_unrelated_user_fields(self):
        customer = make_user()
        make_order(self.branch_a, customer=customer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            set(response.data["results"][0].keys()),
            {
                "id",
                "first_name",
                "last_name",
                "email",
                "phone_number",
                "orders_count",
                "reservations_count",
                "last_activity_at",
            },
        )
