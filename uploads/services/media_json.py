from __future__ import annotations

from uuid import UUID

from core.exceptions.uploads import UploadValidationException
from uploads.models import UploadAsset
from uploads.state import UploadAssetStatus


_MEDIA_STRING_KEYS = {
    "heroImage",
    "image",
    "backgroundImage",
    "coverImage",
    "logo",
    "src",
    "url",
}

_FORBIDDEN_PREFIXES = ("data:", "blob:")


def _is_forbidden_ref(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(_FORBIDDEN_PREFIXES)


def sanitize_media_value(value, *, tenant_id, allow_legacy_urls: bool = True):
    if value is None:
        return None
    if isinstance(value, str):
        if _is_forbidden_ref(value):
            raise UploadValidationException(
                "data: and blob: URLs cannot be persisted as media references."
            )
        if value.startswith("http://") or value.startswith("https://") or value.startswith("/"):
            if not allow_legacy_urls:
                raise UploadValidationException("Legacy media URLs are not accepted.")
            return value
        raise UploadValidationException("Invalid media reference.")
    if isinstance(value, dict):
        asset_id = value.get("asset_id") or value.get("assetId")
        if not asset_id:
            raise UploadValidationException("Media object must include asset_id.")
        try:
            parsed = UUID(str(asset_id))
        except (TypeError, ValueError) as exc:
            raise UploadValidationException("asset_id must be a UUID.") from exc
        asset = UploadAsset.objects.filter(id=parsed).first()
        if asset is None:
            raise UploadValidationException("Unknown media asset_id.")
        if str(asset.tenant_id) != str(tenant_id):
            raise UploadValidationException("Media asset does not belong to this tenant.")
        if asset.purpose != "website_media":
            raise UploadValidationException("Media asset purpose must be website_media.")
        if asset.status not in {
            UploadAssetStatus.READY,
            UploadAssetStatus.ATTACHED,
        }:
            raise UploadValidationException("Media asset is not READY.")
        if asset.status == UploadAssetStatus.READY:
            asset.status = UploadAssetStatus.ATTACHED
            asset.attached_to_type = "website_builder.WebsiteLayout"
            asset.save(update_fields=["status", "attached_to_type", "updated_at"])
        return {"asset_id": str(asset.id)}
    raise UploadValidationException("Invalid media reference type.")


def sanitize_media_tree(data, *, tenant_id):
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            if key in _MEDIA_STRING_KEYS or key.endswith("Image") or key.endswith("Url"):
                if isinstance(value, list):
                    out[key] = [
                        sanitize_media_value(item, tenant_id=tenant_id) for item in value
                    ]
                else:
                    out[key] = sanitize_media_value(value, tenant_id=tenant_id)
            elif key == "gallery" and (value is None or isinstance(value, list)):
                # Media galleries are lists of URLs/asset refs. Template names
                # such as sectionTemplates.gallery = "grid" are not media.
                out[key] = (
                    None
                    if value is None
                    else [sanitize_media_value(item, tenant_id=tenant_id) for item in value]
                )
            else:
                out[key] = sanitize_media_tree(value, tenant_id=tenant_id)
        return out
    if isinstance(data, list):
        return [sanitize_media_tree(item, tenant_id=tenant_id) for item in data]
    if isinstance(data, str) and _is_forbidden_ref(data):
        raise UploadValidationException(
            "data: and blob: URLs cannot be persisted as media references."
        )
    return data


def resolve_media_tree(data):
    """Expand {asset_id} objects to URLs for API responses while keeping asset_id."""
    if isinstance(data, dict):
        asset_id = data.get("asset_id") or data.get("assetId")
        if asset_id and set(data.keys()) <= {"asset_id", "assetId", "url"}:
            asset = UploadAsset.objects.filter(id=asset_id).first()
            url = asset.public_url() if asset else None
            return {"asset_id": str(asset_id), "url": url}
        return {key: resolve_media_tree(value) for key, value in data.items()}
    if isinstance(data, list):
        return [resolve_media_tree(item) for item in data]
    return data
