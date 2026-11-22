"""API tests for GET /api/branches/console-branches/{branch_id}/metrics/."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from access.models import (
    Permission,
    Role,
    RolePermission,
    StaffMembership,
    StaffMembershipStatus,
)
from access.tests.helpers import create_canonical_assignment
from accounts.models import User
from orders.models import (
    Order,
    OrderStatus,
    OrderType,
    PaymentMethod,
    PaymentStatus,
)
from tenants.models import Branch, Owner, Tenant, TenantStatus


METRICS_URL = "/api/branches/console-branches/{branch_id}/metrics/"


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


def make_branch(tenant, **kwargs):
    defaults = {"name": f"Branch {uuid.uuid4().hex[:6]}"}
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


def ensure_role(slug: str) -> Role:
    role, _ = Role.objects.get_or_create(
        slug=slug,
        defaults={"name": slug.title(), "system_role": True},
    )
    return role


def ensure_analytics_view_permission() -> Permission:
    permission, _ = Permission.objects.get_or_create(
        slug="analytics.view",
        defaults={"resource": "analytics", "action": "view"},
    )
    return permission


def grant_role_permission(role: Role, permission: Permission) -> None:
    RolePermission.objects.get_or_create(role=role, permission=permission)


def make_staff_assignment(
    *,
    user,
    tenant,
    branch,
    role_slug="manager",
    membership_status=StaffMembershipStatus.ACTIVE,
):
    """branch=None creates a tenant-wide assignment."""
    role = ensure_role(role_slug)
    permission = ensure_analytics_view_permission()
    grant_role_permission(role, permission)

    membership = StaffMembership.objects.create(
        user=user,
        tenant=tenant,
        status=membership_status,
    )
    if branch is None:
        create_canonical_assignment(
            membership=membership,
            role=role,
            all_locations=True,
        )
    else:
        create_canonical_assignment(
            membership=membership,
            role=role,
            branch=branch,
        )
    return membership


def make_order(branch, **kwargs):
    defaults = {
        "order_number": f"ORD-{uuid.uuid4().hex[:10]}",
        "branch": branch,
        "order_type": OrderType.PICKUP,
        "payment_method": PaymentMethod.CASH,
        "status": OrderStatus.COMPLETED,
        "payment_status": PaymentStatus.PAID,
        "total": Decimal("100.00"),
    }
    defaults.update(kwargs)
    return Order.objects.create(**defaults)


class BranchMetricsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant)
        self.url = METRICS_URL.format(branch_id=self.branch.id)

    def test_normal_branch_metrics(self):
        customer = make_user()
        make_order(self.branch, customer=customer, total=Decimal("200.00"))
        make_order(self.branch, customer=customer, total=Decimal("300.00"))

        staff_user = make_user()
        make_staff_assignment(
            user=staff_user,
            tenant=self.tenant,
            branch=self.branch,
        )

        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["branchId"], str(self.branch.id))
        self.assertEqual(response.data["totalOrders"], 2)
        self.assertEqual(response.data["totalRevenue"], 500.0)
        self.assertEqual(response.data["totalCustomers"], 1)
        self.assertEqual(response.data["staffCount"], 1)
        self.assertEqual(response.data["averageOrderValue"], 250.0)
        self.assertEqual(response.data["totalReservations"], 0)
        self.assertEqual(response.data["period"], "month")
        self.assertEqual(response.data["details"]["paidOrders"], 2)
        self.assertFalse(response.data["details"]["reservation"]["implemented"])

    def test_served_dine_in_order_counts_as_completed(self):
        make_order(
            self.branch,
            order_type=OrderType.DINE_IN,
            status=OrderStatus.SERVED,
        )

        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["details"]["completedOrders"], 1)

    def test_branch_without_orders(self):
        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["totalOrders"], 0)
        self.assertEqual(response.data["totalRevenue"], 0)
        self.assertEqual(response.data["totalCustomers"], 0)
        self.assertEqual(response.data["averageOrderValue"], 0)
        self.assertEqual(response.data["staffCount"], 0)

    def test_cancelled_orders_excluded_from_totals(self):
        customer = make_user()
        make_order(self.branch, customer=customer, total=Decimal("100.00"))
        make_order(
            self.branch,
            customer=customer,
            status=OrderStatus.CANCELLED,
            total=Decimal("999.00"),
        )

        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["totalOrders"], 1)
        self.assertEqual(response.data["totalRevenue"], 100.0)
        self.assertEqual(response.data["details"]["cancelledOrders"], 1)

    def test_refunded_and_failed_payments_excluded_from_revenue(self):
        customer = make_user()
        make_order(self.branch, customer=customer, total=Decimal("50.00"))
        make_order(
            self.branch,
            customer=customer,
            payment_status=PaymentStatus.REFUNDED,
            total=Decimal("80.00"),
        )
        make_order(
            self.branch,
            customer=customer,
            payment_status=PaymentStatus.FAILED,
            total=Decimal("70.00"),
        )

        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["totalOrders"], 1)
        self.assertEqual(response.data["totalRevenue"], 50.0)
        self.assertEqual(response.data["details"]["refundedOrders"], 1)
        self.assertEqual(response.data["details"]["failedPayments"], 1)

    def test_guest_orders_not_counted_as_customers(self):
        make_order(self.branch, customer=None, total=Decimal("40.00"))
        customer = make_user()
        make_order(self.branch, customer=customer, total=Decimal("60.00"))

        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["totalOrders"], 2)
        self.assertEqual(response.data["totalCustomers"], 1)
        self.assertEqual(response.data["details"]["guestOrders"], 1)

    def test_staff_counting_rules(self):
        active_user = make_user()
        suspended_user = make_user()
        tenant_wide_user = make_user()
        deleted_user = make_user(is_deleted=True)

        make_staff_assignment(
            user=active_user,
            tenant=self.tenant,
            branch=self.branch,
        )
        make_staff_assignment(
            user=suspended_user,
            tenant=self.tenant,
            branch=self.branch,
            membership_status=StaffMembershipStatus.SUSPENDED,
        )
        make_staff_assignment(
            user=tenant_wide_user,
            tenant=self.tenant,
            branch=None,
        )
        make_staff_assignment(
            user=deleted_user,
            tenant=self.tenant,
            branch=self.branch,
        )

        self.client.force_authenticate(user=self.owner_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["staffCount"], 2)
        self.assertEqual(response.data["details"]["staff"]["active"], 2)
        self.assertEqual(response.data["details"]["staff"]["inactive"], 1)
        self.assertEqual(
            response.data["details"]["staff"]["tenantWideAssignments"], 1
        )
        self.assertFalse(response.data["details"]["staff"]["managerIncluded"])

    def test_period_filtering_all_vs_day(self):
        customer = make_user()
        old_order = make_order(
            self.branch,
            customer=customer,
            total=Decimal("100.00"),
        )
        Order.objects.filter(pk=old_order.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )

        make_order(self.branch, customer=customer, total=Decimal("50.00"))

        self.client.force_authenticate(user=self.owner_user)

        all_response = self.client.get(self.url, {"period": "all"})
        self.assertEqual(all_response.status_code, 200)
        self.assertEqual(all_response.data["totalOrders"], 2)
        self.assertEqual(all_response.data["period"], "all")

        month_response = self.client.get(self.url, {"period": "month"})
        self.assertEqual(month_response.status_code, 200)
        self.assertEqual(month_response.data["totalOrders"], 1)
        self.assertEqual(month_response.data["period"], "month")

    def test_permission_denied_without_analytics_view(self):
        outsider = make_user()
        other_owner, other_tenant = make_tenant_with_owner()
        other_branch = make_branch(other_tenant)

        staff_user = make_user()
        role = ensure_role("waiter")
        membership = StaffMembership.objects.create(
            user=staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        create_canonical_assignment(
            membership=membership,
            role=role,
            branch=self.branch,
        )

        self.client.force_authenticate(user=outsider)
        response = self.client.get(
            METRICS_URL.format(branch_id=other_branch.id)
        )
        self.assertEqual(response.status_code, 403)

        self.client.force_authenticate(user=staff_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_staff_with_analytics_view_can_access(self):
        staff_user = make_user()
        make_staff_assignment(
            user=staff_user,
            tenant=self.tenant,
            branch=self.branch,
        )

        self.client.force_authenticate(user=staff_user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
