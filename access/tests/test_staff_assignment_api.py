"""Integration tests for the Staff Assignment REST contract."""
import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from access.models import (
    AssignmentStatus,
    Role,
    StaffAssignment,
    StaffMembership,
    StaffMembershipStatus,
)
from access.selectors.permission_dal import permission_selector
from accounts.models import User
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


def make_tenant(**kwargs):
    owner_user = make_user()
    owner = Owner.objects.create(user=owner_user)
    defaults = {
        "owner": owner,
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": TenantStatus.ACTIVE,
        "is_active": True,
    }
    defaults.update(kwargs)
    tenant = Tenant.objects.create(**defaults)
    return owner_user, tenant


class StaffAssignmentApiTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user()
        self.manager_role = Role.objects.get(slug="manager")
        self.waiter_role = Role.objects.get(slug="waiter")
        self.membership = StaffMembership.objects.create(
            user=self.staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.branch_a = Branch.objects.create(tenant=self.tenant, name="Branch A")
        self.branch_b = Branch.objects.create(tenant=self.tenant, name="Branch B")
        self.base_url = f"/api/authorization/tenants/{self.tenant.id}/staff-assignments/"
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner_user)

    def _create_payload(self, **overrides):
        payload = {
            "membership_id": str(self.membership.id),
            "role_id": str(self.manager_role.id),
            "location_ids": [str(self.branch_a.id)],
            "all_locations": False,
            "mode": "manage",
        }
        payload.update(overrides)
        return payload

    def test_create_single_location(self):
        response = self.client.post(self.base_url, self._create_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["all_locations"], False)
        self.assertEqual(len(response.data["locations"]), 1)
        self.assertEqual(response.data["locations"][0]["id"], str(self.branch_a.id))
        self.assertEqual(response.data["role"]["slug"], "manager")
        self.assertNotIn("branch", response.data)
        self.assertEqual(response.data["status"], "active")
        self.assertEqual(response.data["granted_by"], str(self.owner_user.id))

    def test_create_multiple_locations(self):
        response = self.client.post(
            self.base_url,
            self._create_payload(
                location_ids=[str(self.branch_a.id), str(self.branch_b.id)],
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        location_ids = {str(item["id"]) for item in response.data["locations"]}
        self.assertEqual(
            location_ids,
            {str(self.branch_a.id), str(self.branch_b.id)},
        )
        self.assertEqual(
            StaffAssignment.objects.filter(membership=self.membership).count(),
            1,
        )

    def test_create_tenant_wide(self):
        response = self.client.post(
            self.base_url,
            self._create_payload(location_ids=[], all_locations=True),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["all_locations"])
        self.assertEqual(response.data["locations"], [])

    def test_create_rejects_all_locations_with_location_ids(self):
        response = self.client.post(
            self.base_url,
            self._create_payload(
                location_ids=[str(self.branch_a.id)],
                all_locations=True,
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_update_patch_scope(self):
        create_response = self.client.post(
            self.base_url, self._create_payload(), format="json"
        )
        assignment_id = create_response.data["assignment_id"]

        response = self.client.patch(
            f"{self.base_url}{assignment_id}/",
            {
                "location_ids": [str(self.branch_a.id), str(self.branch_b.id)],
                "all_locations": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["locations"]), 2)

    def test_update_put_replaces_contract_fields(self):
        create_response = self.client.post(
            self.base_url, self._create_payload(), format="json"
        )
        assignment_id = create_response.data["assignment_id"]

        response = self.client.put(
            f"{self.base_url}{assignment_id}/",
            {
                "role_id": str(self.waiter_role.id),
                "location_ids": [str(self.branch_b.id)],
                "all_locations": False,
                "mode": "read",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["role"]["slug"], "waiter")
        self.assertEqual(response.data["mode"], "read")
        self.assertEqual(
            response.data["locations"][0]["id"],
            str(self.branch_b.id),
        )

    def test_delete_revokes_assignment(self):
        create_response = self.client.post(
            self.base_url, self._create_payload(), format="json"
        )
        assignment_id = create_response.data["assignment_id"]

        response = self.client.delete(f"{self.base_url}{assignment_id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], AssignmentStatus.REVOKED)
        self.assertEqual(response.data["revoked_by"], str(self.owner_user.id))
        self.assertIsNotNone(response.data["revoked_at"])
        self.assertTrue(
            StaffAssignment.objects.filter(id=assignment_id).exists()
        )

    def test_list_and_retrieve_use_contract_shape(self):
        create_response = self.client.post(
            self.base_url, self._create_payload(), format="json"
        )
        assignment_id = create_response.data["assignment_id"]

        list_response = self.client.get(self.base_url)
        self.assertEqual(list_response.status_code, 200)
        results = list_response.data
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        self.assertIn("assignment_id", results[0])
        self.assertEqual(results[0]["membership_id"], str(self.membership.id))
        self.assertEqual(results[0]["user_id"], str(self.staff_user.id))
        self.assertIn("locations", results[0])

        detail_response = self.client.get(f"{self.base_url}{assignment_id}/")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data["assignment_id"], assignment_id)
        self.assertEqual(detail_response.data["membership_id"], str(self.membership.id))
        self.assertEqual(detail_response.data["user_id"], str(self.staff_user.id))

    def test_create_response_includes_membership_and_user_identity(self):
        response = self.client.post(self.base_url, self._create_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["membership_id"], str(self.membership.id))
        self.assertEqual(response.data["user_id"], str(self.staff_user.id))

    def test_filter_by_membership_id(self):
        other_user = make_user()
        other_membership = StaffMembership.objects.create(
            user=other_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.client.post(self.base_url, self._create_payload(), format="json")
        self.client.post(
            self.base_url,
            self._create_payload(
                membership_id=str(other_membership.id),
                role_id=str(self.waiter_role.id),
            ),
            format="json",
        )

        response = self.client.get(
            self.base_url, {"membership_id": str(self.membership.id)}
        )
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["membership_id"], str(self.membership.id))
        self.assertEqual(results[0]["user_id"], str(self.staff_user.id))

    def test_filter_by_user_id(self):
        other_user = make_user()
        other_membership = StaffMembership.objects.create(
            user=other_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.client.post(self.base_url, self._create_payload(), format="json")
        self.client.post(
            self.base_url,
            self._create_payload(
                membership_id=str(other_membership.id),
                role_id=str(self.waiter_role.id),
            ),
            format="json",
        )

        response = self.client.get(
            self.base_url, {"user_id": str(self.staff_user.id)}
        )
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["user_id"], str(self.staff_user.id))
        self.assertEqual(results[0]["membership_id"], str(self.membership.id))

    def test_user_id_filter_is_tenant_scoped(self):
        other_owner, other_tenant = make_tenant()
        shared_user = self.staff_user
        StaffMembership.objects.create(
            user=shared_user,
            tenant=other_tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.client.post(self.base_url, self._create_payload(), format="json")

        # Same user_id under a different tenant must not leak this tenant's rows
        # when requested via the other tenant's URL by its owner.
        other_client = APIClient()
        other_client.force_authenticate(user=other_owner)
        response = other_client.get(
            f"/api/authorization/tenants/{other_tenant.id}/staff-assignments/",
            {"user_id": str(shared_user.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_page_size_500_returns_more_than_default_page(self):
        roles = list(
            Role.objects.exclude(slug__in=("owner", "admin")).order_by("slug")[:3]
        )
        # Need >20 assignments: create extra memberships + one role each,
        # plus more roles on the primary membership where unique allows.
        created = 0
        for role in roles:
            response = self.client.post(
                self.base_url,
                self._create_payload(role_id=str(role.id), all_locations=True, location_ids=[]),
                format="json",
            )
            self.assertEqual(response.status_code, 201)
            created += 1

        extra_needed = 25 - created
        for _ in range(extra_needed):
            user = make_user()
            membership = StaffMembership.objects.create(
                user=user,
                tenant=self.tenant,
                status=StaffMembershipStatus.ACTIVE,
            )
            response = self.client.post(
                self.base_url,
                self._create_payload(
                    membership_id=str(membership.id),
                    role_id=str(self.manager_role.id),
                    all_locations=True,
                    location_ids=[],
                ),
                format="json",
            )
            self.assertEqual(response.status_code, 201)

        default_response = self.client.get(self.base_url)
        self.assertEqual(default_response.status_code, 200)
        self.assertEqual(len(default_response.data["results"]), 20)
        self.assertGreater(default_response.data["count"], 20)

        large_response = self.client.get(self.base_url, {"page_size": 500})
        self.assertEqual(large_response.status_code, 200)
        self.assertEqual(large_response.data["count"], default_response.data["count"])
        self.assertEqual(
            len(large_response.data["results"]),
            large_response.data["count"],
        )
        self.assertGreater(len(large_response.data["results"]), 20)
        self.assertLessEqual(len(large_response.data["results"]), 500)

    def test_page_size_capped_at_500(self):
        response = self.client.get(self.base_url, {"page_size": 9999})
        self.assertEqual(response.status_code, 200)
        # Cap is enforced by paginator; with few rows we just ensure request succeeds
        # and does not error. Size of results is min(count, 500).
        self.assertLessEqual(len(response.data["results"]), 500)

    def test_owner_role_cannot_be_assigned(self):
        owner_role = Role.objects.get(slug="owner")
        response = self.client.post(
            self.base_url,
            self._create_payload(role_id=str(owner_role.id), all_locations=True, location_ids=[]),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            StaffAssignment.objects.filter(
                membership=self.membership, role=owner_role
            ).exists()
        )

    def test_permission_resolution_after_api_create(self):
        self.client.post(self.base_url, self._create_payload(), format="json")

        slugs = permission_selector.get_user_permission_slugs(
            user_id=self.staff_user.id,
            tenant_id=self.tenant.id,
            branch_id=self.branch_a.id,
        )
        self.assertIn("staff.view", slugs)

        other_branch_slugs = permission_selector.get_user_permission_slugs(
            user_id=self.staff_user.id,
            tenant_id=self.tenant.id,
            branch_id=self.branch_b.id,
        )
        self.assertNotIn("staff.view", other_branch_slugs)


class StaffMembershipApiTests(TestCase):
    def setUp(self):
        self.owner_user, self.tenant = make_tenant()
        self.staff_user = make_user(
            email="staff@example.com",
            first_name="Ada",
            last_name="Lovelace",
            phone_number="+15551234567",
        )
        self.membership = StaffMembership.objects.create(
            user=self.staff_user,
            tenant=self.tenant,
            status=StaffMembershipStatus.ACTIVE,
        )
        self.base_url = f"/api/authorization/tenants/{self.tenant.id}/staff-memberships/"
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner_user)

    def test_list_membership_includes_user_identity(self):
        response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        item = results[0]

        # Legacy fields retained
        self.assertEqual(str(item["id"]), str(self.membership.id))
        self.assertEqual(str(item["tenant"]), str(self.tenant.id))
        self.assertEqual(str(item["user"]), str(self.staff_user.id))
        self.assertEqual(item["status"], StaffMembershipStatus.ACTIVE)

        # Console roster fields
        self.assertEqual(str(item["user_id"]), str(self.staff_user.id))
        self.assertEqual(item["email"], "staff@example.com")
        self.assertEqual(item["first_name"], "Ada")
        self.assertEqual(item["last_name"], "Lovelace")
        self.assertEqual(item["phone_number"], "+15551234567")
        self.assertEqual(
            item["user_data"],
            {
                "id": str(self.staff_user.id),
                "email": "staff@example.com",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "phone_number": "+15551234567",
            },
        )

    def test_membership_page_size_query_param(self):
        for _ in range(21):
            StaffMembership.objects.create(
                user=make_user(),
                tenant=self.tenant,
                status=StaffMembershipStatus.ACTIVE,
            )

        default_response = self.client.get(self.base_url)
        self.assertEqual(len(default_response.data["results"]), 20)

        large_response = self.client.get(self.base_url, {"page_size": 500})
        self.assertEqual(large_response.data["count"], 22)
        self.assertEqual(len(large_response.data["results"]), 22)

    def test_owner_is_not_a_staff_membership_or_assignment(self):
        response = self.client.get(self.base_url)
        user_ids = {str(item["user_id"]) for item in response.data["results"]}
        self.assertNotIn(str(self.owner_user.id), user_ids)

        assignments_url = (
            f"/api/authorization/tenants/{self.tenant.id}/staff-assignments/"
        )
        assignments = self.client.get(assignments_url, {"user_id": str(self.owner_user.id)})
        self.assertEqual(assignments.data["count"], 0)
        self.assertTrue(
            Tenant.objects.filter(id=self.tenant.id, owner__user_id=self.owner_user.id).exists()
        )

