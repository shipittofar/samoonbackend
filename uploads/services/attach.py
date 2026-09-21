from __future__ import annotations

from django.utils import timezone

from core.exceptions.uploads import (
    UploadNotFoundException,
    UploadPermissionDeniedException,
    UploadStateException,
    UploadValidationException,
)
from uploads.models import UploadAsset
from uploads.purposes import get_purpose
from uploads.state import UploadAssetStatus, can_transition


def _mark(asset: UploadAsset, status: str, **fields) -> None:
    if asset.status != status and not can_transition(asset.status, status):
        raise UploadStateException(
            f"Cannot transition upload from {asset.status} to {status}."
        )
    asset.status = status
    for name, value in fields.items():
        setattr(asset, name, value)
    update = ["status", "updated_at", *fields.keys()]
    asset.save(update_fields=list(dict.fromkeys(update)))


def detach_asset(asset: UploadAsset | None) -> None:
    if asset is None:
        return
    if asset.status == UploadAssetStatus.DETACHED:
        return
    if asset.status == UploadAssetStatus.ATTACHED:
        _mark(asset, UploadAssetStatus.DETACHED, detached_at=timezone.now())
        return
    if asset.status == UploadAssetStatus.READY:
        _mark(asset, UploadAssetStatus.DETACHED, detached_at=timezone.now())


def get_ready_asset(*, asset_id, user, purpose: str, tenant_id=None) -> UploadAsset:
    asset = UploadAsset.objects.filter(id=asset_id).first()
    if asset is None:
        raise UploadNotFoundException()
    if asset.purpose != purpose:
        raise UploadValidationException("Upload purpose does not match this field.")
    if asset.status not in {UploadAssetStatus.READY, UploadAssetStatus.ATTACHED}:
        raise UploadStateException("Upload must be READY before it can be attached.")
    if asset.is_expired() and asset.status != UploadAssetStatus.ATTACHED:
        raise UploadStateException("Upload has expired.")
    policy = get_purpose(purpose)
    if policy.tenant_required:
        if tenant_id is None or str(asset.tenant_id) != str(tenant_id):
            raise UploadPermissionDeniedException(
                "Upload does not belong to this tenant."
            )
    else:
        if asset.created_by_id != user.id:
            raise UploadPermissionDeniedException(
                "Upload does not belong to this user."
            )
    return asset


def assign_image_from_asset(instance, field_name: str, asset: UploadAsset) -> None:
    key = asset.public_key
    getattr(instance, field_name).name = key


def clear_image_field(instance, field_name: str) -> None:
    setattr(instance, field_name, None)


def attach_asset_to_instance(
    *,
    instance,
    image_field: str,
    asset_fk: str,
    asset: UploadAsset | None,
    user,
    purpose: str,
    tenant_id=None,
    attached_to_type: str = "",
) -> list[str]:
    """
    Attach or detach an asset. Does not save the instance.
    Returns model field names that were mutated.
    """
    update_fields = [image_field, asset_fk]
    previous_id = getattr(instance, f"{asset_fk}_id", None)
    previous = None
    if previous_id:
        previous = UploadAsset.objects.filter(pk=previous_id).first()
    if asset is None:
        if previous:
            detach_asset(previous)
        setattr(instance, asset_fk, None)
        clear_image_field(instance, image_field)
        return update_fields

    ready = get_ready_asset(
        asset_id=asset.id if isinstance(asset, UploadAsset) else asset,
        user=user,
        purpose=purpose,
        tenant_id=tenant_id,
    )
    if previous and previous.id != ready.id:
        detach_asset(previous)
    setattr(instance, asset_fk, ready)
    assign_image_from_asset(instance, image_field, ready)
    _mark(
        ready,
        UploadAssetStatus.ATTACHED,
        attached_to_type=attached_to_type or instance._meta.label,
        attached_to_id=str(instance.pk or ""),
    )
    return update_fields
