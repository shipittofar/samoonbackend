"""HTTP tests for tenant+branch scoped pending reservation counts."""
import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from access.models import StaffMembership, StaffMembershipStatus
from access.tests.helpers import create_canonical_assignment, get_role
from accounts.models import User
from reservations.models import Reservation, ReservationStatus
from tenants.models import Branch, Owner, Tenant, TenantStatus


PENDING_COUNT_URL = (
    "/api/reservations/console-reservations/tenants/{tenant_id}/"
    "branches/{branch_id}/pending-count/"
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
    defaults = {
        "name": f"Branch {uuid.uuid4().hex[:6]}",
        "reservations_enabled": True,
    }
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


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


class ConsolePendingReservationCountTests(TestCase):
    def setUp(self):
        self.owner_a, self.tenant_a = make_tenant_with_owner()
        self.branch_a = make_branch(self.tenant_a, name="A")
        self.branch_b = make_branch(self.tenant_a, name="B")
        self.owner_b, self.tenant_b = make_tenant_with_owner()
        self.branch_tenant_b = make_branch(self.tenant_b, name="TB-A")

        for _ in range(2):
            make_reservation(self.branch_a, status=ReservationStatus.PENDING)
        make_reservation(self.branch_a, status=ReservationStatus.CONFIRMED)
        make_reservation(self.branch_a, status=ReservationStatus.CANCELLED)
        make_reservation(self.branch_a, status=ReservationStatus.COMPLETED)

        for _ in range(4):
            make_reservation(self.branch_b, status=ReservationStatus.PENDING)
        make_reservation(self.branch_b, status=ReservationStatus.SEATED)

        for _ in range(8):
            make_reservation(self.branch_tenant_b, status=ReservationStatus.PENDING)

        self.client = APIClient()

    def url(self, tenant, branch):
        return PENDING_COUNT_URL.format(tenant_id=tenant.id, branch_id=branch.id)

    def test_owner_count_branch_a(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(self.url(self.tenant_a, self.branch_a))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 2})

    def test_owner_count_branch_b(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(self.url(self.tenant_a, self.branch_b))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 4})

    def test_other_tenant_owner_count(self):
        self.client.force_authenticate(user=self.owner_b)
        response = self.client.get(self.url(self.tenant_b, self.branch_tenant_b))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 8})

    def test_zero_pending(self):
        empty_owner, empty_tenant = make_tenant_with_owner()
        empty_branch = make_branch(empty_tenant)
        make_reservation(empty_branch, status=ReservationStatus.CONFIRMED)
        self.client.force_authenticate(user=empty_owner)
        response = self.client.get(self.url(empty_tenant, empty_branch))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"count": 0})

    def test_owner_cannot_query_other_tenant(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(self.url(self.tenant_b, self.branch_tenant_b))
        self.assertEqual(response.status_code, 403, response.data)

    def test_mismatched_tenant_and_branch(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(self.url(self.tenant_a, self.branch_tenant_b))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["error"]["code"], "branch_not_found")

    def test_staff_with_reservations_view_on_branch_a_only(self):
        support = make_user()
        assign_role(support, self.tenant_a, "support", branch=self.branch_a)
        self.client.force_authenticate(user=support)

        allowed = self.client.get(self.url(self.tenant_a, self.branch_a))
        self.assertEqual(allowed.status_code, 200, allowed.data)
        self.assertEqual(allowed.data, {"count": 2})

        denied = self.client.get(self.url(self.tenant_a, self.branch_b))
        self.assertEqual(denied.status_code, 403, denied.data)

    def test_kitchen_without_reservations_view_is_denied(self):
        kitchen = make_user()
        assign_role(kitchen, self.tenant_a, "kitchen", branch=self.branch_a)
        self.client.force_authenticate(user=kitchen)
        response = self.client.get(self.url(self.tenant_a, self.branch_a))
        self.assertEqual(response.status_code, 403, response.data)

    def test_no_unscoped_admin_list(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get("/api/reservations/?admin=true")
        self.assertEqual(response.status_code, 405)

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
        self.assertEqual(response.data, {"count": 2})
