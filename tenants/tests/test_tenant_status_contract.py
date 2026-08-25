"""Tenant visibility (is_active) and usability (status) contract across API responses."""
import uuid

from django.core.cache import cache
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Favorite, User
from accounts.services.favorite_bll import FavoriteBusinessLogicLayer
from menu.models import MenuCategory, MenuItem
from orders.models import Order
from tenants.models import Branch, Owner, Tenant, TenantStatus
from tenants.services import BranchBusinessLogicLayer, TenantBusinessLogicLayer


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


class TenantStatusContractTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user, self.owner = make_owner_user()
        self.client.force_authenticate(user=self.user)

    def _create_tenant(self, **kwargs):
        defaults = {"name": f"Tenant {uuid.uuid4().hex[:6]}"}
        defaults.update(kwargs)
        return TenantBusinessLogicLayer.create_tenant(user=self.user, **defaults)

    def test_create_tenant_response_includes_is_active_and_status(self):
        response = self.client.post(
            "/api/tenants/create/",
            data={"name": f"Contract {uuid.uuid4().hex[:6]}"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("is_active", response.data)
        self.assertIn("status", response.data)
        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["status"], TenantStatus.INACTIVE)

    def test_public_tenant_list_includes_is_active_and_status(self):
        tenant = Tenant.objects.create(
            owner=self.owner,
            name="Public Visible",
            status=TenantStatus.ACTIVE,
            is_active=True,
        )
        Branch.objects.create(tenant=tenant, name="Main")

        response = APIClient().get("/api/tenants/")
        self.assertEqual(response.status_code, 200)
        item = next(i for i in response.data["results"] if i["id"] == str(tenant.id))
        self.assertTrue(item["is_active"])
        self.assertEqual(item["status"], TenantStatus.ACTIVE)

    def test_discover_includes_is_active_and_status(self):
        tenant = Tenant.objects.create(
            owner=self.owner,
            name="Discover Tenant",
            status=TenantStatus.ACTIVE,
            is_active=True,
        )
        Branch.objects.create(tenant=tenant, name="Main", marketplace_visible=True)

        response = APIClient().get("/api/public/discover/")
        item = next(i for i in response.data["results"] if i["id"] == str(tenant.id))
        self.assertTrue(item["is_active"])
        self.assertEqual(item["status"], TenantStatus.ACTIVE)

    def test_branch_response_includes_nested_tenant_state(self):
        tenant = self._create_tenant()
        branch = BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=tenant.id,
            name="Branch One",
        )
        tenant.status = TenantStatus.ACTIVE
        tenant.is_active = False
        tenant.save(update_fields=["status", "is_active"])

        response = self.client.get(f"/api/tenants/{tenant.id}/branches/{branch.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("tenant", response.data)
        self.assertFalse(response.data["tenant"]["is_active"])
        self.assertEqual(response.data["tenant"]["status"], TenantStatus.ACTIVE)

    def test_order_response_includes_tenant_state(self):
        tenant = self._create_tenant()
        branch = BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=tenant.id,
            name="Order Branch",
        )
        tenant.refresh_from_db()
        tenant.status = TenantStatus.ACTIVE
        tenant.is_active = False
        tenant.save(update_fields=["status", "is_active"])

        from decimal import Decimal

        from orders.api.serializers.response import OrderResponseSerializer
        from orders.models import Order, OrderItem, OrderType, PaymentMethod

        category = MenuCategory.objects.create(branch=branch, name="Food")
        item = MenuItem.objects.create(
            branch=branch,
            category=category,
            name="Burger",
            price=Decimal("10.00"),
        )
        order = Order.objects.create(
            customer=self.user,
            branch=branch,
            order_number=f"ORD-{uuid.uuid4().hex[:8]}",
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
            subtotal=Decimal("10.00"),
            total=Decimal("10.00"),
        )
        OrderItem.objects.create(
            order=order,
            menu_item=item,
            name=item.name,
            quantity=1,
            unit_price=item.price,
            total_price=item.price,
        )
        order = Order.objects.select_related("branch__tenant").get(pk=order.pk)
        data = OrderResponseSerializer(order).data

        self.assertFalse(data["tenant_is_active"])
        self.assertEqual(data["tenant_status"], TenantStatus.ACTIVE)
        self.assertFalse(data["tenant"]["is_active"])
        self.assertEqual(data["tenant"]["status"], TenantStatus.ACTIVE)

    def test_favorite_response_includes_tenant_state(self):
        tenant = self._create_tenant()
        branch = BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=tenant.id,
            name="Fav Branch",
        )
        tenant.status = TenantStatus.ACTIVE
        tenant.is_active = False
        tenant.save(update_fields=["status", "is_active"])

        category = MenuCategory.objects.create(branch=branch, name="Food")
        item = MenuItem.objects.create(
            branch=branch,
            category=category,
            name="Pizza",
            price="12.00",
        )
        FavoriteBusinessLogicLayer.add_favorite(user=self.user, menu_item_id=item.id)

        response = self.client.get("/api/users/favorites/")
        self.assertEqual(response.status_code, 200)
        favorite = response.data["results"][0]
        self.assertFalse(favorite["tenant"]["is_active"])
        self.assertEqual(favorite["tenant"]["status"], TenantStatus.ACTIVE)

    def test_auth_me_membership_includes_tenant_state(self):
        tenant = self._create_tenant()
        tenant.status = TenantStatus.INACTIVE
        tenant.is_active = True
        tenant.save(update_fields=["status", "is_active"])

        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        membership = next(
            m for m in response.data["memberships"] if m["tenantId"] == str(tenant.id)
        )
        self.assertTrue(membership["tenantIsActive"])
        self.assertEqual(membership["tenantStatus"], TenantStatus.INACTIVE)
        self.assertEqual(membership["tenant"]["status"], TenantStatus.INACTIVE)

    def test_menu_categories_summary_includes_tenant_state(self):
        tenant = self._create_tenant()
        branch = BranchBusinessLogicLayer.create_branch(
            user=self.user,
            tenant_id=tenant.id,
            name="Menu Branch",
        )
        tenant.status = TenantStatus.ACTIVE
        tenant.is_active = False
        tenant.save(update_fields=["status", "is_active"])

        category = MenuCategory.objects.create(branch=branch, name="Food")
        MenuItem.objects.create(
            branch=branch,
            category=category,
            name="Salad",
            price="8.00",
        )

        response = APIClient().get(f"/api/menu/{branch.id}/categories-with-items/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("tenant", response.data)
        self.assertFalse(response.data["tenant"]["is_active"])
        self.assertEqual(response.data["tenant"]["status"], TenantStatus.ACTIVE)
