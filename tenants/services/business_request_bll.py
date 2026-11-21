"""Business registration requests: file, approve, reject.

See tenants/models/business_request.py.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from access.authorization.platform import is_platform_superuser
from core.exceptions import PermissionDeniedException
from tenants.models import BusinessRequest, BusinessRequestStatus, Owner
from tenants.models.tenant import OwnerStatus


def may_create_business_directly(user) -> bool:
    """Who may skip the request: platform superusers and approved owners
    (an owner profile that is not suspended). Everyone else files a request."""
    if is_platform_superuser(user):
        return True
    return Owner.objects.filter(user_id=user.id).exclude(status=OwnerStatus.SUSPENDED).exists()


def file_request(*, user, **data) -> BusinessRequest:
    if BusinessRequest.objects.filter(user=user, status=BusinessRequestStatus.PENDING).exists():
        raise ValidationError({"detail": "You already have a request waiting for review."})
    return BusinessRequest.objects.create(user=user, **data)


def _assert_decider(actor) -> None:
    if not is_platform_superuser(actor):
        raise PermissionDeniedException("Only a platform superuser can review business requests.")


def _lock_pending(request_id) -> BusinessRequest:
    item = BusinessRequest.objects.select_for_update().select_related("user").get(pk=request_id)
    if item.status != BusinessRequestStatus.PENDING:
        raise ValidationError({"detail": "This request was already reviewed."})
    return item


@transaction.atomic
def approve(*, request_id, actor) -> BusinessRequest:
    """Create the owner profile, the business and its first branch from the
    request. The applicant completes the rest in the console."""
    from tenants.services.tenant_bll import BranchBusinessLogicLayer, TenantBusinessLogicLayer

    _assert_decider(actor)
    item = _lock_pending(request_id)
    applicant = item.user
    if not applicant.is_active or applicant.is_deleted:
        raise ValidationError({"detail": "The applicant's account is no longer active."})

    owner, _ = Owner.objects.get_or_create(user=applicant)
    if owner.status in (None, "", OwnerStatus.PENDING_VERIFICATION):
        owner.status = OwnerStatus.ACTIVE
        owner.verified_at = timezone.now()
        owner.save(update_fields=["status", "verified_at"])
    elif owner.status == OwnerStatus.SUSPENDED:
        raise ValidationError({"detail": "The applicant's owner profile is suspended."})

    tenant = TenantBusinessLogicLayer.create_tenant(
        applicant,
        name=item.name,
        description=item.description,
        business_types=[item.business_type],
    )
    branch_data = {
        "name": item.name,
        "phone": item.phone,
        "city": item.city,
        "address": item.address,
    }
    if item.latitude is not None and item.longitude is not None:
        branch_data["latitude"] = item.latitude
        branch_data["longitude"] = item.longitude
    if item.service_radius_km:
        branch_data["delivery_radius_km"] = item.service_radius_km
    BranchBusinessLogicLayer.create_branch(applicant, tenant.id, **branch_data)

    item.status = BusinessRequestStatus.APPROVED
    item.tenant = tenant
    item.decided_by = actor
    item.decided_at = timezone.now()
    item.save(update_fields=["status", "tenant", "decided_by", "decided_at", "updated_at"])
    return item


@transaction.atomic
def reject(*, request_id, actor, reason: str = "") -> BusinessRequest:
    _assert_decider(actor)
    item = _lock_pending(request_id)
    item.status = BusinessRequestStatus.REJECTED
    item.rejection_reason = (reason or "").strip()
    item.decided_by = actor
    item.decided_at = timezone.now()
    item.save(update_fields=["status", "rejection_reason", "decided_by", "decided_at", "updated_at"])
    return item
