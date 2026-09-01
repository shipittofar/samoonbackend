"""Phase 3 audit locks: feature JSON, Owner.plan, and RBAC stay independent.

These tests document current backend behavior. They are not a new
entitlement architecture.
"""
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from access.constants.rbac_seed import ROLE_PERMISSIONS
from access.models import StaffMembership, StaffMembershipStatus
from access.services.assignment_bll import assignment_bll
from access.services.rbac_bll import rbac_bll
from access.tests.helpers import get_role, make_tenant, make_user
from core.exceptions.orders import OrderingDisabledException
from menu.models import MenuCategory, MenuItem
from orders.models import OrderType, PaymentMethod
from orders.services.orders_bll import OrdersBusinessLogicLayer
from tenants.models import Branch, Tenant
from tenants.services.tenant_bll import TenantBusinessLogicLayer


class FeatureFlagsAreNotAuthorizationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_disabled_feature_flags_do_not_remove_owner_permissions(self):
        owner_user, tenant = make_tenant()
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={
                "featureFlags": {
                    "menu.enabled": False,
                    "analytics.enabled": False,
                    "promotions.enabled": False,
                    "reservations.enabled": False,
                },
                "features": {
                    "menu": False,
                    "orders": False,
                    "loyalty": False,
                    "reports": False,
                    "inventory": False,
                },
            }
        )
        tenant.refresh_from_db()
        cache.clear()

        effective = set(rbac_bll.get_effective_permissions(user=owner_user, tenant=tenant))
        self.assertIn("menu.view", effective)
        self.assertIn("menu.manage", effective)
        self.assertIn("orders.create", effective)
        self.assertIn("analytics.view", effective)
        self.assertIn("promotions.view", effective)
        self.assertIn("reservations.view", effective)
        self.assertIn("loyalty.view", effective)
        self.assertIn("featureflags.manage", effective)
        self.assertEqual(effective, ROLE_PERMISSIONS["owner"])

    def test_waiter_keeps_reservations_permissions_when_flag_is_false(self):
        owner_user, tenant = make_tenant()
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={"featureFlags": {"reservations.enabled": False}}
        )
        staff_user = make_user()
        membership = StaffMembership.objects.create(
            user=staff_user,
            tenant=tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        assignment_bll.create_assignment(
            membership_id=membership.id,
            role_id=get_role("waiter").id,
            all_locations=True,
        )
        cache.clear()

        effective = set(rbac_bll.get_effective_permissions(user=staff_user, tenant=tenant))
        self.assertIn("reservations.view", effective)
        self.assertIn("reservations.manage", effective)
        self.assertEqual(effective, ROLE_PERMISSIONS["waiter"])


class OwnerPlanHasNoRuntimeEnforcementTests(TestCase):
    def test_plan_is_exposed_on_me_but_does_not_limit_tenant_create(self):
        owner_user, tenant = make_tenant()
        owner = tenant.owner
        owner.plan = "free"
        owner.max_tenants = 1
        owner.save(update_fields=["plan", "max_tenants"])

        second = TenantBusinessLogicLayer.create_tenant(
            user=owner_user, name="Second Tenant Despite Plan"
        )
        self.assertIsNotNone(second.id)
        self.assertEqual(Tenant.objects.filter(owner=owner).count(), 2)

    def test_plan_does_not_change_owner_effective_permissions(self):
        owner_user, tenant = make_tenant()
        tenant.owner.plan = "enterprise"
        tenant.owner.save(update_fields=["plan"])
        cache.clear()

        effective = set(rbac_bll.get_effective_permissions(user=owner_user, tenant=tenant))
        self.assertEqual(effective, ROLE_PERMISSIONS["owner"])


class FeaturesJsonIsNotBranchCapabilityTests(TestCase):
    def test_features_orders_true_does_not_enable_disabled_branch_ordering(self):
        owner_user, tenant = make_tenant()
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={"features": {"orders": True, "menu": True}}
        )
        branch = Branch.objects.create(
            tenant=tenant,
            name="Closed Ordering",
            ordering_enabled=False,
            pickup_enabled=True,
        )
        category = MenuCategory.objects.create(branch=branch, name="Mains")
        item = MenuItem.objects.create(
            branch=branch, category=category, name="Burger", price=Decimal("10.00")
        )

        with self.assertRaises(OrderingDisabledException):
            OrdersBusinessLogicLayer().create_order(
                customer=make_user(),
                validated_data={
                    "branch_id": branch.id,
                    "order_type": OrderType.PICKUP,
                    "payment_method": PaymentMethod.CASH,
                    "items": [{"menu_item_id": item.id, "quantity": 1}],
                },
            )


class GetFeatureFlagIsJsonReaderOnlyTests(TestCase):
    def test_get_feature_flag_does_not_consult_rbac_or_plan(self):
        owner_user, tenant = make_tenant()
        tenant.owner.plan = "pro"
        tenant.owner.save(update_fields=["plan"])
        Tenant.objects.filter(pk=tenant.pk).update(
            settings={"featureFlags": {"menu.enabled": False}}
        )
        tenant.refresh_from_db()

        self.assertFalse(tenant.get_feature_flag("menu.enabled"))
        self.assertIn(
            "menu.view",
            rbac_bll.get_effective_permissions(user=owner_user, tenant=tenant),
        )
