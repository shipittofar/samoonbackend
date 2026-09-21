from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.exceptions.uploads import (
    UploadConflictException,
    UploadNotFoundException,
    UploadObjectMissingException,
    UploadStateException,
    UploadValidationException,
)
from uploads import object_store
from uploads.authorization import assert_purpose_authorized, user_can_menu_manage
from uploads.keys import original_storage_key, safe_extension, safe_original_filename
from uploads.models import UploadAsset
from uploads.processing import decode_image
from uploads.purposes import get_purpose
from uploads.state import (
    IDEMPOTENT_COMPLETE_STATUSES,
    UNATTACHED_EXPIRE_STATUSES,
    UploadAssetStatus,
    can_transition,
)


def _intent_ttl():
    hours = getattr(settings, "UPLOADS_INTENT_TTL_HOURS", 24)
    return timedelta(hours=hours)


def _presign_expires() -> int:
    return int(getattr(settings, "UPLOADS_PRESIGN_EXPIRES", 900))


def _max_open_intents() -> int:
    return int(getattr(settings, "UPLOADS_MAX_OPEN_INTENTS_PER_USER", 20))


def _extension_for(filename: str, mime_type: str) -> str:
    ext = safe_extension(filename)
    mime_map = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    if not ext:
        ext = mime_map.get(mime_type, "")
    return ext


def validate_declared_file(*, policy, filename: str, mime_type: str, byte_size: int) -> str:
    if byte_size <= 0:
        raise UploadValidationException("byte_size must be greater than 0.")
    if byte_size > policy.max_bytes:
        raise UploadValidationException(
            f"File exceeds maximum size of {policy.max_bytes} bytes."
        )
    if mime_type not in policy.allowed_mime_types:
        raise UploadValidationException("MIME type is not allowed for this purpose.")
    ext = _extension_for(filename, mime_type)
    if ext not in policy.allowed_extensions:
        raise UploadValidationException("File extension is not allowed for this purpose.")
    if ext == "svg" or mime_type == "image/svg+xml":
        raise UploadValidationException("SVG uploads are not allowed.")
    return ext


def initiate_upload(
    *,
    user,
    purpose: str,
    filename: str,
    mime_type: str,
    byte_size: int,
    checksum: str = "",
    tenant_id=None,
    entity_type: str = "",
    entity_id: str = "",
    idempotency_key: str | None = None,
    branch_id=None,
) -> tuple[UploadAsset, dict]:
    policy = get_purpose(purpose)
    validate_declared_file(
        policy=policy, filename=filename, mime_type=mime_type, byte_size=byte_size
    )

    resolved_branch_id = branch_id or (entity_id if entity_type in {"branch", "menu_item", "menu_category", "menu_tag"} else None)
    if policy.authz == "menu" and not resolved_branch_id:
        resolved_branch_id = entity_id
    assert_purpose_authorized(
        user=user,
        policy=policy,
        tenant_id=tenant_id,
        branch_id=resolved_branch_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    open_count = UploadAsset.objects.filter(
        created_by=user,
        status=UploadAssetStatus.INITIATED,
    ).count()
    if open_count >= _max_open_intents():
        raise UploadValidationException("Too many in-flight uploads. Complete or cancel existing ones.")

    if idempotency_key:
        existing = UploadAsset.objects.filter(
            created_by=user, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            if existing.purpose != purpose or existing.byte_size != byte_size:
                raise UploadConflictException("Idempotency key already used for a different upload.")
            return existing, object_store.generate_presigned_put(
                key=existing.storage_key,
                content_type=existing.mime_type,
                expires_in=_presign_expires(),
            )

    asset = UploadAsset(
        created_by=user,
        tenant_id=tenant_id if policy.tenant_required else None,
        purpose=purpose,
        original_filename=safe_original_filename(filename),
        mime_type=mime_type,
        byte_size=byte_size,
        checksum=checksum or "",
        status=UploadAssetStatus.INITIATED,
        idempotency_key=idempotency_key or None,
        entity_type=entity_type or "",
        entity_id=str(entity_id or ""),
        expires_at=timezone.now() + _intent_ttl(),
    )
    asset.storage_key = original_storage_key(
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        user_id=user.id,
    )
    asset.save()
    upload = object_store.generate_presigned_put(
        key=asset.storage_key,
        content_type=mime_type,
        expires_in=_presign_expires(),
    )
    return asset, upload


def get_asset_for_actor(asset_id, user) -> UploadAsset:
    asset = UploadAsset.objects.filter(id=asset_id).first()
    if asset is None:
        raise UploadNotFoundException()
    if asset.created_by_id != user.id:
        if asset.tenant_id:
            from uploads.authorization import user_can_settings_edit

            if user_can_settings_edit(user, asset.tenant_id):
                return asset
            if asset.purpose.startswith("menu") and asset.entity_id:
                from tenants.models import Branch

                branch = Branch.objects.filter(id=asset.entity_id).first()
                if branch and user_can_menu_manage(user, branch):
                    return asset
        from core.exceptions.uploads import UploadPermissionDeniedException

        raise UploadPermissionDeniedException()
    return asset


def _transition(asset: UploadAsset, target: str) -> None:
    if asset.status == target:
        return
    if not can_transition(asset.status, target):
        raise UploadStateException(
            f"Cannot transition upload from {asset.status} to {target}."
        )
    asset.status = target


def complete_upload(*, asset_id, user) -> UploadAsset:
    with transaction.atomic():
        asset = (
            UploadAsset.objects.select_for_update()
            .filter(id=asset_id)
            .first()
        )
        if asset is None:
            raise UploadNotFoundException()
        get_asset_for_actor(asset_id, user)

        if asset.status in IDEMPOTENT_COMPLETE_STATUSES:
            return asset
        if asset.status in {UploadAssetStatus.EXPIRED, UploadAssetStatus.DETACHED}:
            raise UploadStateException("This upload can no longer be completed.")
        if asset.is_expired() and asset.status == UploadAssetStatus.INITIATED:
            _transition(asset, UploadAssetStatus.EXPIRED)
            asset.save(update_fields=["status", "updated_at"])
            raise UploadStateException("Upload intent has expired.")

        meta = object_store.head_object(asset.storage_key)
        if meta is None:
            raise UploadObjectMissingException()
        actual_size = int(meta.get("content_length") or 0)
        if actual_size and actual_size != asset.byte_size:
            asset.failure_code = "size_mismatch"
            asset.failure_message = (
                f"Declared size {asset.byte_size} does not match stored size {actual_size}."
            )
            _transition(asset, UploadAssetStatus.FAILED)
            asset.save()
            raise UploadValidationException(asset.failure_message)

        stored_type = (meta.get("content_type") or "").split(";")[0].strip()
        if stored_type and stored_type not in {"binary/octet-stream", "application/octet-stream"}:
            if stored_type != asset.mime_type:
                asset.failure_code = "mime_mismatch"
                asset.failure_message = "Stored Content-Type does not match the declared MIME type."
                _transition(asset, UploadAssetStatus.FAILED)
                asset.save()
                raise UploadValidationException(asset.failure_message)

        policy = get_purpose(asset.purpose)
        if policy.require_image:
            try:
                with object_store.open_object(asset.storage_key) as fh:
                    decode_image(fh)
            except Exception:
                asset.failure_code = "invalid_image"
                asset.failure_message = "Stored object is not a valid image."
                _transition(asset, UploadAssetStatus.FAILED)
                asset.save()
                raise UploadValidationException(asset.failure_message)

        if asset.checksum:
            digest = sha256()
            with object_store.open_object(asset.storage_key) as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    digest.update(chunk)
            if digest.hexdigest() != asset.checksum.lower():
                asset.failure_code = "checksum_mismatch"
                asset.failure_message = "Checksum does not match the stored object."
                _transition(asset, UploadAssetStatus.FAILED)
                asset.save()
                raise UploadValidationException(asset.failure_message)

        _transition(asset, UploadAssetStatus.UPLOADED)
        asset.uploaded_at = timezone.now()
        asset.failure_code = ""
        asset.failure_message = ""
        asset.save()
        asset_id_str = str(asset.id)

    from uploads.tasks import process_upload_asset

    process_upload_asset.delay(asset_id_str)
    return UploadAsset.objects.get(pk=asset_id_str)


def cancel_upload(*, asset_id, user) -> UploadAsset:
    with transaction.atomic():
        asset = UploadAsset.objects.select_for_update().filter(id=asset_id).first()
        if asset is None:
            raise UploadNotFoundException()
        get_asset_for_actor(asset_id, user)
        if asset.status == UploadAssetStatus.ATTACHED:
            raise UploadStateException("Attached uploads cannot be cancelled.")
        if asset.status in {UploadAssetStatus.EXPIRED, UploadAssetStatus.DETACHED}:
            return asset
        if asset.status == UploadAssetStatus.READY:
            _transition(asset, UploadAssetStatus.DETACHED)
            asset.detached_at = timezone.now()
        else:
            _transition(asset, UploadAssetStatus.EXPIRED)
        asset.save()
        keys = [asset.storage_key, *list((asset.variant_keys or {}).values())]
    for key in keys:
        object_store.delete_object(key)
    return asset


def expire_unattached_assets() -> int:
    now = timezone.now()
    expired_count = 0
    qs = UploadAsset.objects.filter(
        status__in=UNATTACHED_EXPIRE_STATUSES,
        expires_at__lte=now,
    )
    for asset_id in qs.values_list("id", flat=True):
        with transaction.atomic():
            asset = UploadAsset.objects.select_for_update().filter(id=asset_id).first()
            if asset is None:
                continue
            if asset.status == UploadAssetStatus.ATTACHED:
                continue
            if asset.status not in UNATTACHED_EXPIRE_STATUSES:
                continue
            if not asset.expires_at or asset.expires_at > timezone.now():
                continue
            keys = [asset.storage_key, *list((asset.variant_keys or {}).values())]
            _transition(asset, UploadAssetStatus.EXPIRED)
            asset.save(update_fields=["status", "updated_at"])
            expired_count += 1
        for key in keys:
            object_store.delete_object(key)
    return expired_count
