"""Marketplace home page hero: background images + slideshow timing.

Stored as PlatformSetting(key="homepage.hero"). Mirrors the frontend's
normalizePlatformHomepageHero (src/lib/platform-homepage-store.ts): same
fields, same clamping, so what the superuser saves is what visitors get.

Uploaded images (``assetId``) come from the shared upload pipeline as
purpose=website_media, entity platform/homepage, no tenant. Saving marks them
ATTACHED so the orphan-upload cleanup never deletes a live hero image, and
releases (DETACHED) the ones the new hero no longer uses.
"""
from __future__ import annotations

from uuid import UUID

from django.db import transaction
from rest_framework.exceptions import ValidationError

from platform_settings.models import PlatformSetting

HERO_KEY = "homepage.hero"
ATTACHED_TO_TYPE = "platform_settings.homepage_hero"
ATTACHED_TO_ID = "homepage"

MAX_IMAGES = 12
MIN_INTERVAL_MS, MAX_INTERVAL_MS, DEFAULT_INTERVAL_MS = 2000, 60_000, 7000
MIN_TRANSITION_MS, MAX_TRANSITION_MS, DEFAULT_TRANSITION_MS = 200, 3000, 900
POSITIONS = {"center", "top", "bottom", "left", "right"}


def _clamp(raw, lo: int, hi: int, default: int) -> int:
    try:
        n = round(float(raw))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, n))


def _hero_asset(asset_id):
    """The upload behind ``assetId``, if it is a usable platform hero image."""
    from uploads.authorization import is_platform_homepage_media
    from uploads.models import UploadAsset
    from uploads.state import UploadAssetStatus

    try:
        parsed = UUID(str(asset_id))
    except (TypeError, ValueError):
        raise ValidationError({"backgroundImages": "assetId must be a UUID."})
    asset = UploadAsset.objects.filter(id=parsed).first()
    if asset is None or not is_platform_homepage_media(
        purpose=asset.purpose,
        entity_type=asset.entity_type,
        entity_id=asset.entity_id,
        tenant_id=asset.tenant_id,
    ):
        raise ValidationError({"backgroundImages": "Unknown homepage image upload."})
    if asset.status not in {UploadAssetStatus.READY, UploadAssetStatus.ATTACHED}:
        raise ValidationError({"backgroundImages": "An image is still being processed; try again shortly."})
    if asset.status == UploadAssetStatus.READY and asset.is_expired():
        raise ValidationError({"backgroundImages": "An uploaded image has expired; upload it again."})
    return asset


def _clean_image(raw, order: int, assets: dict):
    if not isinstance(raw, dict):
        return None
    src = raw.get("src") if isinstance(raw.get("src"), str) else ""
    src = src.strip()
    asset_id = raw.get("assetId") or raw.get("asset_id")
    if asset_id:
        asset = _hero_asset(asset_id)
        assets[str(asset.id)] = asset
        src = asset.public_url() or src
        asset_id = str(asset.id)
    if not src:
        return None
    lowered = src.lower()
    if lowered.startswith(("data:", "blob:")) or not (
        lowered.startswith(("https://", "http://")) or src.startswith("/")
    ):
        raise ValidationError({"backgroundImages": "Image src must be an http(s) URL or a site path."})
    if len(src) > 2000:
        raise ValidationError({"backgroundImages": "Image src is too long."})

    image_id = raw.get("id") if isinstance(raw.get("id"), str) and raw.get("id").strip() else f"platform-hero-{order}"
    image = {
        "id": image_id.strip()[:100],
        "src": src,
        "order": order,
        "enabled": raw.get("enabled") is not False,
    }
    if asset_id:
        image["assetId"] = asset_id
    alt = raw.get("altText")
    if isinstance(alt, str) and alt.strip():
        image["altText"] = alt.strip()[:300]
    for key in ("objectPosition", "objectPositionMobile"):
        if raw.get(key) in POSITIONS:
            image[key] = raw[key]
    return image


def _normalize(raw) -> tuple[dict, dict]:
    if not isinstance(raw, dict):
        raise ValidationError("The hero must be a JSON object.")
    images_raw = raw.get("backgroundImages") or []
    if not isinstance(images_raw, list):
        raise ValidationError({"backgroundImages": "Must be a list."})
    if len(images_raw) > MAX_IMAGES:
        raise ValidationError({"backgroundImages": f"At most {MAX_IMAGES} images."})
    assets: dict = {}
    images = []
    for item in images_raw:
        image = _clean_image(item, len(images), assets)
        if image is not None:
            images.append(image)
    hero = {
        "backgroundImages": images,
        "slideshowIntervalMs": _clamp(raw.get("slideshowIntervalMs"), MIN_INTERVAL_MS, MAX_INTERVAL_MS, DEFAULT_INTERVAL_MS),
        "slideshowTransitionMs": _clamp(
            raw.get("slideshowTransitionMs"), MIN_TRANSITION_MS, MAX_TRANSITION_MS, DEFAULT_TRANSITION_MS
        ),
    }
    return hero, assets


def _asset_ids(hero: dict | None) -> set[str]:
    return {img["assetId"] for img in (hero or {}).get("backgroundImages", []) if img.get("assetId")}


def get_hero() -> dict | None:
    """The saved hero, or None when a superuser has never saved one."""
    row = PlatformSetting.objects.filter(key=HERO_KEY).first()
    if row is None:
        return None
    hero = dict(row.value or {})
    # URLs follow the current storage settings (e.g. a new CDN domain).
    ids = _asset_ids(hero)
    if ids:
        from uploads.models import UploadAsset

        urls = {str(a.id): a.public_url() for a in UploadAsset.objects.filter(id__in=ids)}
        hero["backgroundImages"] = [
            {**img, "src": urls.get(img.get("assetId")) or img["src"]} for img in hero.get("backgroundImages", [])
        ]
    return hero


def save_hero(*, user, data) -> dict:
    from uploads.services.attach import detach_asset
    from uploads.models import UploadAsset
    from uploads.state import UploadAssetStatus

    hero, assets = _normalize(data)
    with transaction.atomic():
        row = PlatformSetting.objects.select_for_update().filter(key=HERO_KEY).first()
        previous_ids = _asset_ids(row.value if row else None)
        if row is None:
            row = PlatformSetting(key=HERO_KEY)
        row.value = hero
        row.updated_by = user if getattr(user, "is_authenticated", False) else None
        row.save()

        for asset in assets.values():
            if asset.status == UploadAssetStatus.READY:
                asset.status = UploadAssetStatus.ATTACHED
                asset.attached_to_type = ATTACHED_TO_TYPE
                asset.attached_to_id = ATTACHED_TO_ID
                asset.save(update_fields=["status", "attached_to_type", "attached_to_id", "updated_at"])
        for gone in UploadAsset.objects.filter(id__in=previous_ids - set(assets)):
            detach_asset(gone)
    return hero
