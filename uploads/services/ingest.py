from __future__ import annotations

from core.exceptions.uploads import UploadConflictException, UploadValidationException
from uploads.keys import safe_original_filename
from uploads.object_store import save_bytes
from uploads.purposes import get_purpose
from uploads.services.upload_bll import complete_upload, initiate_upload, validate_declared_file


def ingest_uploaded_file(
    *,
    user,
    uploaded_file,
    purpose: str,
    tenant_id=None,
    entity_type: str = "",
    entity_id: str = "",
    branch_id=None,
):
    """Server-side compatibility path: persist bytes then run complete/process."""
    policy = get_purpose(purpose)
    filename = getattr(uploaded_file, "name", "") or "upload"
    mime_type = getattr(uploaded_file, "content_type", "") or ""
    byte_size = getattr(uploaded_file, "size", None)
    if byte_size is None:
        uploaded_file.seek(0, 2)
        byte_size = uploaded_file.tell()
        uploaded_file.seek(0)
    if not mime_type:
        raise UploadValidationException("MIME type is required.")
    validate_declared_file(
        policy=policy,
        filename=filename,
        mime_type=mime_type,
        byte_size=byte_size,
    )
    asset, _upload = initiate_upload(
        user=user,
        purpose=purpose,
        filename=safe_original_filename(filename),
        mime_type=mime_type,
        byte_size=byte_size,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        branch_id=branch_id,
    )
    uploaded_file.seek(0)
    save_bytes(asset.storage_key, uploaded_file, content_type=mime_type)
    return complete_upload(asset_id=asset.id, user=user)


def reject_conflicting_file_and_asset(file_provided: bool, asset_provided: bool) -> None:
    if file_provided and asset_provided:
        raise UploadConflictException(
            "Provide either an asset id or a legacy file, not both."
        )
