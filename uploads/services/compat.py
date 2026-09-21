from __future__ import annotations

from django.conf import settings

from uploads.services.attach import attach_asset_to_instance
from uploads.services.ingest import ingest_uploaded_file, reject_conflicting_file_and_asset


def uploads_direct_enabled() -> bool:
    return bool(getattr(settings, "UPLOADS_DIRECT", True))


def apply_image_input(
    *,
    instance,
    user,
    image_field: str,
    asset_fk: str,
    purpose: str,
    tenant_id=None,
    file=None,
    file_provided: bool = False,
    asset_id=None,
    asset_id_provided: bool = False,
    entity_type: str = "",
    entity_id: str = "",
    branch_id=None,
    ingest_legacy: bool = True,
) -> list[str]:
    """
    Mutates instance image field / asset FK. Does not save.

    omitted = unchanged (empty list)
    null asset or null file = detach
    asset_id = attach
    legacy file = ingest into upload domain when ingest_legacy else assign FileField
    """
    reject_conflicting_file_and_asset(file_provided, asset_id_provided)
    if not file_provided and not asset_id_provided:
        return []

    if asset_id_provided:
        return attach_asset_to_instance(
            instance=instance,
            image_field=image_field,
            asset_fk=asset_fk,
            asset=asset_id,
            user=user,
            purpose=purpose,
            tenant_id=tenant_id,
            attached_to_type=entity_type,
        )

    if file is None:
        return attach_asset_to_instance(
            instance=instance,
            image_field=image_field,
            asset_fk=asset_fk,
            asset=None,
            user=user,
            purpose=purpose,
            tenant_id=tenant_id,
            attached_to_type=entity_type,
        )

    if ingest_legacy and uploads_direct_enabled():
        asset = ingest_uploaded_file(
            user=user,
            uploaded_file=file,
            purpose=purpose,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id or str(getattr(instance, "pk", "") or ""),
            branch_id=branch_id,
        )
        return attach_asset_to_instance(
            instance=instance,
            image_field=image_field,
            asset_fk=asset_fk,
            asset=asset,
            user=user,
            purpose=purpose,
            tenant_id=tenant_id,
            attached_to_type=entity_type,
        )

    previous = getattr(instance, asset_fk, None)
    if previous:
        from uploads.services.attach import detach_asset

        detach_asset(previous)
        setattr(instance, asset_fk, None)
    setattr(instance, image_field, file)
    return [image_field, asset_fk]
