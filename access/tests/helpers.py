"""Shared test helpers for access app tests."""
from __future__ import annotations

import uuid

from access.models import (
    AssignmentMode,
    AssignmentStatus,
    Role,
    StaffAssignment,
    StaffAssignmentLocation,
    StaffMembership,
    StaffMembershipStatus,
)
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


def make_tenant(*, with_active_status=True, **kwargs):
    owner_user = make_user()
    owner = Owner.objects.create(user=owner_user)
    defaults = {
        "owner": owner,
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": TenantStatus.ACTIVE if with_active_status else TenantStatus.CLOSED,
        "is_active": with_active_status,
    }
    defaults.update(kwargs)
    tenant = Tenant.objects.create(**defaults)
    return owner_user, tenant


def make_membership(*, user, tenant, status=StaffMembershipStatus.ACTIVE):
    return StaffMembership.objects.create(
        user=user,
        tenant=tenant,
        status=status,
    )


def make_branch(tenant, **kwargs):
    defaults = {"name": f"Branch {uuid.uuid4().hex[:6]}"}
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


def create_canonical_assignment(
    *,
    membership,
    role,
    branch=None,
    branch_ids=None,
    all_locations=False,
    granted_by=None,
    status=AssignmentStatus.ACTIVE,
):
    assignment = StaffAssignment.objects.create(
        membership=membership,
        role=role,
        all_locations=all_locations,
        status=status,
        mode=AssignmentMode.MANAGE,
        granted_by=granted_by,
    )
    if all_locations:
        return assignment

    target_branch_ids = branch_ids or ([branch.id] if branch else [])
    StaffAssignmentLocation.objects.bulk_create(
        [
            StaffAssignmentLocation(assignment=assignment, branch_id=branch_id)
            for branch_id in target_branch_ids
        ]
    )
    return assignment


def get_role(slug: str) -> Role:
    return Role.objects.get(slug=slug)
