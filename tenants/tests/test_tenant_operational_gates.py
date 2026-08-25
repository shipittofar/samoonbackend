"""Regression tests for tenant operational availability gates (is_active + status)."""
import uuid
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from addresses.domain.address_type import AddressType
from menu.models import MenuCategory, MenuItem
from orders.models import Order, OrderType, PaymentMethod
from tenants.models import Branch, Owner, Tenant, TenantStatus


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


def make_operational_tenant(**overrides):
    owner = Owner.objects.create(user=make_user())
    defaults = {
        "owner": owner,
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": TenantStatus.ACTIVE,
        "is_active": True,
    }
    defaults.update(overrides)
    return Tenant.objects.create(**defaults)


def make_branch(tenant, **overrides):
    defaults = {
        "name": f"Branch {uuid.uuid4().hex[:6]}",
        "pickup_enabled": True,
        "delivery_enabled": True,
        "delivery_radius_km": 50,
        "latitude": Decimal("34.050000"),
        "longitude": Decimal("-118.250000"),
        "cash_on_delivery_enabled": True,
    }
    defaults.update(overrides)
    return Branch.objects.create(tenant=tenant, **defaults)


def make_menu_item(branch):
    category = MenuCategory.objects.create(branch=branch, name="Mains")
    return MenuItem.objects.create(
        branch=branch,
        category=category,
        name="Burger",
        price=Decimal("10.00"),
    )


def valid_address_payload(**overrides):
    payload = {
        "address_type": AddressType.HOME,
        "country": "US",
        "province": "CA",
        "city": "Los Angeles",
        "street": "123 Main St",
        "postal_code": "90001",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "is_default": True,
    }
    payload.update(overrides)
    return payload


class TenantOperationalGateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = make_user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.customer)

    def _order_payload(self, branch, item):
        return {
            "branch_id": str(branch.id),
            "order_type": OrderType.PICKUP,
            "payment_method": PaymentMethod.CASH,
            "items": [{"menu_item_id": str(item.id), "quantity": 1}],
        }

    def _discount_payload(self, branch):
        return {
            "branch_id": str(branch.id),
            "discount_code": "SAVE10",
        }

    def _create_address(self):
        response = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data["id"]

    def _serviceability_get(self, address_id, branch_id):
        return self.client.get(
            f"/api/users/addresses/{address_id}/serviceability/",
            {"branch_id": str(branch_id)},
        )

    def _serviceability_post(self, branch_id, address_id=None, **delivery_overrides):
        payload = {"branch_id": str(branch_id)}
        if address_id is not None:
            payload["address_id"] = str(address_id)
        else:
            payload["delivery_address"] = {
                "street": "123 Main St",
                "city": "Los Angeles",
                "postal_code": "90001",
                "latitude": 34.0522,
                "longitude": -118.2437,
            }
        payload.update(delivery_overrides)
        return self.client.post(
            "/api/users/addresses/check-serviceability/",
            payload,
            format="json",
        )

    def test_case_a_operational_tenant_can_create_order(self):
        tenant = make_operational_tenant()
        branch = make_branch(tenant)
        item = make_menu_item(branch)

        response = self.client.post(
            "/api/orders/",
            self._order_payload(branch, item),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_case_b_hidden_tenant_cannot_create_order(self):
        tenant = make_operational_tenant(is_active=False, status=TenantStatus.ACTIVE)
        branch = make_branch(tenant)
        item = make_menu_item(branch)

        response = self.client.post(
            "/api/orders/",
            self._order_payload(branch, item),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_b_hidden_tenant_cannot_validate_discount(self):
        tenant = make_operational_tenant(is_active=False, status=TenantStatus.ACTIVE)
        branch = make_branch(tenant)

        response = self.client.post(
            "/api/orders/validate-discount/",
            self._discount_payload(branch),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_b_hidden_tenant_fails_serviceability_get(self):
        tenant = make_operational_tenant(is_active=False, status=TenantStatus.ACTIVE)
        branch = make_branch(tenant)
        address_id = self._create_address()

        response = self._serviceability_get(address_id, branch.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_b_hidden_tenant_fails_serviceability_post(self):
        tenant = make_operational_tenant(is_active=False, status=TenantStatus.ACTIVE)
        branch = make_branch(tenant)
        address_id = self._create_address()

        response = self._serviceability_post(branch.id, address_id=address_id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_e_hidden_inactive_tenant_cannot_create_order(self):
        tenant = make_operational_tenant(
            is_active=False,
            status=TenantStatus.INACTIVE,
        )
        branch = make_branch(tenant)
        item = make_menu_item(branch)

        response = self.client.post(
            "/api/orders/",
            self._order_payload(branch, item),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_hidden_tenant_public_retrieve_returns_not_found(self):
        tenant = make_operational_tenant(is_active=False, status=TenantStatus.ACTIVE)

        response = APIClient().get(f"/api/tenants/{tenant.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_tenant_retrieve_ignores_stale_cache_visibility(self):
        from tenants.selectors import TenantDataAccessLayer

        tenant = make_operational_tenant()
        make_branch(tenant)
        TenantDataAccessLayer.get_tenant_by_id(tenant.id)

        tenant.is_active = False
        tenant.save(update_fields=["is_active"])

        response = APIClient().get(f"/api/tenants/{tenant.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_status_public_retrieve_returns_not_found(self):
        tenant = make_operational_tenant(status=TenantStatus.INACTIVE)
        make_branch(tenant)

        response = APIClient().get(f"/api/tenants/{tenant.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_scoped_branch_deep_link_exposes_tenant_state(self):
        """Deep-link branch endpoints intentionally bypass public catalog filters."""
        tenant = make_operational_tenant(is_active=False, status=TenantStatus.ACTIVE)
        branch = make_branch(tenant)

        response = APIClient().get(f"/api/tenants/{tenant.id}/branches/{branch.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["tenant"]["is_active"])
        self.assertEqual(response.data["tenant"]["status"], TenantStatus.ACTIVE)

    def test_inactive_status_fails_serviceability_post(self):
        tenant = make_operational_tenant(status=TenantStatus.INACTIVE)
        branch = make_branch(tenant)
        address_id = self._create_address()

        response = self._serviceability_post(branch.id, address_id=address_id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_closed_status_fails_serviceability_post(self):
        tenant = make_operational_tenant(status=TenantStatus.CLOSED)
        branch = make_branch(tenant)
        address_id = self._create_address()

        response = self._serviceability_post(branch.id, address_id=address_id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_b_hidden_tenant_excluded_from_public_branch_list(self):
        visible = make_operational_tenant(name="Visible")
        hidden = make_operational_tenant(name="Hidden", is_active=False)
        visible_branch = make_branch(visible)
        make_branch(hidden)

        response = APIClient().get("/api/tenants/branches/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertIn(str(visible_branch.id), ids)
        self.assertEqual(len(ids), 1)

    def test_case_c_inactive_status_cannot_create_order(self):
        tenant = make_operational_tenant(status=TenantStatus.INACTIVE)
        branch = make_branch(tenant)
        item = make_menu_item(branch)

        response = self.client.post(
            "/api/orders/",
            self._order_payload(branch, item),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_c_inactive_status_cannot_validate_discount(self):
        tenant = make_operational_tenant(status=TenantStatus.INACTIVE)
        branch = make_branch(tenant)

        response = self.client.post(
            "/api/orders/validate-discount/",
            self._discount_payload(branch),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_c_inactive_status_fails_serviceability(self):
        tenant = make_operational_tenant(status=TenantStatus.INACTIVE)
        branch = make_branch(tenant)
        address_id = self._create_address()

        response = self._serviceability_get(address_id, branch.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_d_closed_status_cannot_create_order(self):
        tenant = make_operational_tenant(status=TenantStatus.CLOSED)
        branch = make_branch(tenant)
        item = make_menu_item(branch)

        response = self.client.post(
            "/api/orders/",
            self._order_payload(branch, item),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_d_closed_status_cannot_validate_discount(self):
        tenant = make_operational_tenant(status=TenantStatus.CLOSED)
        branch = make_branch(tenant)

        response = self.client.post(
            "/api/orders/validate-discount/",
            self._discount_payload(branch),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_d_closed_status_fails_serviceability(self):
        tenant = make_operational_tenant(status=TenantStatus.CLOSED)
        branch = make_branch(tenant)
        address_id = self._create_address()

        response = self._serviceability_get(address_id, branch.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_case_e_hidden_inactive_tenant_not_on_public_branch_list(self):
        tenant = make_operational_tenant(
            is_active=False,
            status=TenantStatus.INACTIVE,
        )
        make_branch(tenant)

        response = APIClient().get("/api/tenants/branches/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_hidden_tenant_public_website_returns_not_found(self):
        tenant = make_operational_tenant(is_active=False)
        url = f"/api/public/websites/{tenant.id}/"

        response = APIClient().get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_menu_popular_includes_tenant_summary(self):
        tenant = make_operational_tenant(is_active=False, status=TenantStatus.ACTIVE)
        branch = make_branch(tenant)
        make_menu_item(branch)

        response = APIClient().get(f"/api/menu/{branch.id}/items/popular/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("tenant", response.data)
        self.assertFalse(response.data["tenant"]["is_active"])
        self.assertEqual(response.data["tenant"]["status"], TenantStatus.ACTIVE)

    def test_menu_search_alias_includes_tenant_summary(self):
        tenant = make_operational_tenant(is_active=False, status=TenantStatus.ACTIVE)
        branch = make_branch(tenant)
        make_menu_item(branch)

        response = APIClient().get(
            "/api/menu/items/search/",
            {"branch_id": str(branch.id), "q": "Burger"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("tenant", response.data)
        self.assertIn("results", response.data)
        self.assertFalse(response.data["tenant"]["is_active"])

    def test_menu_category_detail_includes_tenant_summary(self):
        tenant = make_operational_tenant(is_active=False, status=TenantStatus.ACTIVE)
        branch = make_branch(tenant)
        category = MenuCategory.objects.create(branch=branch, name="Mains")

        response = APIClient().get(
            f"/api/menu/categories/{branch.id}/{category.id}/",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("tenant", response.data)
        self.assertFalse(response.data["tenant"]["is_active"])
        self.assertEqual(response.data["tenant"]["status"], TenantStatus.ACTIVE)

    def test_update_order_blocked_when_tenant_becomes_inactive(self):
        tenant = make_operational_tenant()
        branch = make_branch(tenant)
        item = make_menu_item(branch)

        create_response = self.client.post(
            "/api/orders/",
            self._order_payload(branch, item),
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        order_id = create_response.data["id"]

        tenant.status = TenantStatus.INACTIVE
        tenant.save(update_fields=["status", "updated_at"])

        update_response = self.client.patch(
            f"/api/orders/{order_id}/",
            self._order_payload(branch, item),
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Order.objects.filter(pk=order_id, status="pending").exists())

    def test_update_order_blocked_when_tenant_becomes_hidden(self):
        tenant = make_operational_tenant()
        branch = make_branch(tenant)
        item = make_menu_item(branch)

        create_response = self.client.post(
            "/api/orders/",
            self._order_payload(branch, item),
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        order_id = create_response.data["id"]

        tenant.is_active = False
        tenant.save(update_fields=["is_active", "updated_at"])

        update_response = self.client.patch(
            f"/api/orders/{order_id}/",
            self._order_payload(branch, item),
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Order.objects.filter(pk=order_id, status="pending").exists())
