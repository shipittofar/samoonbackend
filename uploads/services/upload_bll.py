from __future__ import annotations

from hmac import compare_digest
from datetime import timedelta
from hashlib import sha256
import logging
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.exceptions.uploads import (
    UploadConflictException,
    UploadExpiredException,
    UploadNotFoundException,
    UploadObjectMissingException,
    UploadPermissionDeniedException,
    UploadStateException,
    UploadValidationException,
)
from uploads import object_store
from uploads.authorization import assert_purpose_authorized, is_platform_homepage_media, resolve_branch_id
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

logger = logging.getLogger(__name__)

_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_IDEMPOTENT_REISSUE = {UploadAssetStatus.INITIATED}


def _log(event: str, asset: UploadAsset, **extra) -> None:
    parts = " ".join(f"{key}={value}" for key, value in extra.items())
    logger.info(
        "%s asset_id=%s tenant_id=%s purpose=%s status=%s %s",
        event,
        asset.id,
        asset.tenant_id,
        asset.purpose,
        asset.status,
        parts,
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


def _validate_checksum(checksum: str) -> str:
    if not checksum:
        return ""
    if not _SHA256_HEX.fullmatch(checksum):
        raise UploadValidationException("checksum must be a SHA-256 hex digest.")
    return checksum.lower()


def assert_actor_can_access_asset(asset: UploadAsset, user) -> None:
    policy = get_purpose(asset.purpose)
    if policy.authz == "self":
        if asset.created_by_id != user.id:
            raise UploadPermissionDeniedException()
        return
    # Always re-authorize from the persisted asset context so platform homepage
    # (tenant_id=null, entity_type=platform, entity_id=homepage) is not
    # re-interpreted as a branch/tenant upload on complete/cancel/status.
    assert_purpose_authorized(
        user=user,
        policy=policy,
        tenant_id=asset.tenant_id,
        branch_id=None
        if is_platform_homepage_media(
            purpose=asset.purpose,
            entity_type=asset.entity_type,
            entity_id=asset.entity_id,
            tenant_id=asset.tenant_id,
        )
        else resolve_branch_id(
            entity_type=asset.entity_type,
            entity_id=asset.entity_id,
        ),
        entity_type=asset.entity_type,
        entity_id=asset.entity_id,
    )


def get_asset_for_actor(asset_id, user) -> UploadAsset:
    asset = UploadAsset.objects.filter(id=asset_id).first()
    if asset is None:
        raise UploadNotFoundException()
    assert_actor_can_access_asset(asset, user)
    return asset


def _transition(asset: UploadAsset, target: str) -> None:
    if asset.status == target:
        return
    if not can_transition(asset.status, target):
        raise UploadStateException(
            f"Cannot transition upload from {asset.status} to {target}."
        )
    asset.status = target


def _expected_storage_key(asset: UploadAsset) -> str:
    return original_storage_key(
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        user_id=asset.created_by_id,
    )


def _verify_stored_object(asset: UploadAsset) -> None:
    expected_key = _expected_storage_key(asset)
    if asset.storage_key != expected_key:
        raise UploadValidationException("Upload object key does not match this asset.")

    meta = object_store.head_object(asset.storage_key)
    if meta is None:
        raise UploadObjectMissingException()

    actual_size = int(meta.get("content_length") or 0)
    if actual_size != asset.byte_size:
        raise UploadValidationException(
            f"Declared size {asset.byte_size} does not match stored size {actual_size}."
        )

    stored_type = (meta.get("content_type") or "").split(";")[0].strip()
    if stored_type and stored_type not in {"binary/octet-stream", "application/octet-stream"}:
        if stored_type != asset.mime_type:
            raise UploadValidationException(
                "Stored Content-Type does not match the declared MIME type."
            )

    policy = get_purpose(asset.purpose)
    if policy.require_image:
        try:
            with object_store.open_object(asset.storage_key) as fh:
                decode_image(fh, expected_mime=asset.mime_type)
        except Exception as exc:
            raise UploadValidationException("Stored object is not a valid image.") from exc

    if asset.checksum:
        digest = sha256()
        with object_store.open_object(asset.storage_key) as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if not compare_digest(actual, asset.checksum.lower()):
            raise UploadValidationException("Checksum does not match the stored object.")


def _fail_asset(asset: UploadAsset, code: str, message: str) -> None:
    asset.failure_code = code
    asset.failure_message = message
    _transition(asset, UploadAssetStatus.FAILED)
    asset.save()
    _log("upload_complete_failed", asset, failure_code=code)
    raise UploadValidationException(message)


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
    checksum = _validate_checksum(checksum or "")

    resolved_branch_id = resolve_branch_id(
        branch_id=branch_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
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
            if existing.status not in _IDEMPOTENT_REISSUE or existing.is_expired():
                raise UploadConflictException(
                    "Idempotency key already used and cannot issue another upload URL."
                )
            _log("upload_initiate_idempotent", existing)
            return existing, object_store.generate_presigned_put(
                key=existing.storage_key,
                content_type=existing.mime_type,
                expires_in=_presign_expires(),
                public=policy.public_object,
            )

    stored_entity_type = entity_type or ""
    stored_entity_id = str(entity_id or "")
    if policy.authz in {"menu", "branch_settings"} and resolved_branch_id and not stored_entity_id:
        stored_entity_type = stored_entity_type or "branch"
        stored_entity_id = str(resolved_branch_id)

    platform_homepage = is_platform_homepage_media(
        purpose=purpose,
        entity_type=stored_entity_type,
        entity_id=stored_entity_id,
        tenant_id=tenant_id,
    )
    # Persist the canonical platform context (tenant null) so complete/ready/attach
    # re-authorize from the same markers and never fall into branch_settings.
    stored_tenant_id = None if platform_homepage else (tenant_id if policy.tenant_required else None)

    asset = UploadAsset(
        created_by=user,
        tenant_id=stored_tenant_id,
        purpose=purpose,
        original_filename=safe_original_filename(filename),
        mime_type=mime_type,
        byte_size=byte_size,
        checksum=checksum,
        status=UploadAssetStatus.INITIATED,
        idempotency_key=idempotency_key or None,
        entity_type=stored_entity_type,
        entity_id=stored_entity_id,
        expires_at=timezone.now() + _intent_ttl(),
    )
    asset.storage_key = original_storage_key(
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        user_id=user.id,
    )
    try:
        with transaction.atomic():
            asset.save()
    except IntegrityError as exc:
        if not idempotency_key:
            raise
        existing = UploadAsset.objects.filter(
            created_by=user, idempotency_key=idempotency_key
        ).first()
        if existing is None:
            raise UploadConflictException("Upload idempotency conflict.") from exc
        if existing.status not in _IDEMPOTENT_REISSUE or existing.is_expired():
            raise UploadConflictException(
                "Idempotency key already used and cannot issue another upload URL."
            ) from exc
        return existing, object_store.generate_presigned_put(
            key=existing.storage_key,
            content_type=existing.mime_type,
            expires_in=_presign_expires(),
            public=get_purpose(existing.purpose).public_object,
        )

    upload = object_store.generate_presigned_put(
        key=asset.storage_key,
        content_type=mime_type,
        expires_in=_presign_expires(),
        public=policy.public_object,
    )
    _log("upload_initiated", asset)
    return asset, upload


def complete_upload(*, asset_id, user) -> UploadAsset:
    """Verify the stored object. Client flags such as uploaded=true are ignored."""
    asset = get_asset_for_actor(asset_id, user)
    if asset.status in IDEMPOTENT_COMPLETE_STATUSES:
        _log("upload_complete_idempotent", asset)
        return asset
    if asset.status in {UploadAssetStatus.EXPIRED, UploadAssetStatus.DETACHED}:
        raise UploadStateException("This upload can no longer be completed.")
    if asset.is_expired() and asset.status == UploadAssetStatus.INITIATED:
        with transaction.atomic():
            locked = UploadAsset.objects.select_for_update().filter(id=asset_id).first()
            if locked is None:
                raise UploadNotFoundException()
            if locked.status == UploadAssetStatus.INITIATED and locked.is_expired():
                _transition(locked, UploadAssetStatus.EXPIRED)
                locked.save(update_fields=["status", "updated_at"])
                _log("upload_expired", locked)
        raise UploadExpiredException()

    verification_error: UploadValidationException | None = None
    try:
        _verify_stored_object(asset)
    except UploadObjectMissingException:
        raise
    except UploadValidationException as exc:
        verification_error = exc

    with transaction.atomic():
        locked = UploadAsset.objects.select_for_update().filter(id=asset_id).first()
        if locked is None:
            raise UploadNotFoundException()
        assert_actor_can_access_asset(locked, user)
        if locked.status in IDEMPOTENT_COMPLETE_STATUSES:
            return locked
        if locked.status in {UploadAssetStatus.EXPIRED, UploadAssetStatus.DETACHED}:
            raise UploadStateException("This upload can no longer be completed.")
        if locked.is_expired() and locked.status == UploadAssetStatus.INITIATED:
            _transition(locked, UploadAssetStatus.EXPIRED)
            locked.save(update_fields=["status", "updated_at"])
            _log("upload_expired", locked)
            raise UploadExpiredException()
        if verification_error is not None:
            message = str(verification_error)
            lowered = message.lower()
            code = "invalid_object"
            if "size" in lowered:
                code = "size_mismatch"
            elif "content-type" in lowered or "mime" in lowered:
                code = "mime_mismatch"
            elif "checksum" in lowered:
                code = "checksum_mismatch"
            elif "image" in lowered or "format" in lowered:
                code = "invalid_image"
            _fail_asset(locked, code, message)
        _transition(locked, UploadAssetStatus.UPLOADED)
        locked.uploaded_at = timezone.now()
        locked.failure_code = ""
        locked.failure_message = ""
        locked.save()
        _log("upload_completed", locked)
        asset_id_str = str(locked.id)

    from uploads.tasks import process_upload_asset

    process_upload_asset.delay(asset_id_str)
    return UploadAsset.objects.get(pk=asset_id_str)


def cancel_upload(*, asset_id, user) -> UploadAsset:
    keys: list[str] = []
    with transaction.atomic():
        asset = UploadAsset.objects.select_for_update().filter(id=asset_id).first()
        if asset is None:
            raise UploadNotFoundException()
        assert_actor_can_access_asset(asset, user)
        if asset.status == UploadAssetStatus.ATTACHED:
            raise UploadStateException("Attached uploads cannot be cancelled.")
        if asset.status in {UploadAssetStatus.EXPIRED, UploadAssetStatus.DETACHED}:
            _log("upload_cancel_idempotent", asset)
            return asset
        keys = [asset.storage_key, *list((asset.variant_keys or {}).values())]
        _transition(asset, UploadAssetStatus.EXPIRED)
        asset.save()
        _log("upload_cancelled", asset)
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
        keys: list[str] = []
        with transaction.atomic():
            asset = UploadAsset.objects.select_for_update().filter(id=asset_id).first()
            if asset is None:
                continue
            if asset.status == UploadAssetStatus.ATTACHED:
                continue
            if asset.status == UploadAssetStatus.DETACHED:
                continue
            if asset.status not in UNATTACHED_EXPIRE_STATUSES:
                continue
            if not asset.expires_at or asset.expires_at > timezone.now():
                continue
            keys = [asset.storage_key, *list((asset.variant_keys or {}).values())]
            _transition(asset, UploadAssetStatus.EXPIRED)
            asset.save(update_fields=["status", "updated_at"])
            _log("upload_expired", asset)
            expired_count += 1
        for key in keys:
            object_store.delete_object(key)
    return expired_count
