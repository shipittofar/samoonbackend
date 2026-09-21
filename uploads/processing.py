from __future__ import annotations

import io
import logging

from PIL import Image
from django.core.files.base import ContentFile

from uploads.keys import variant_storage_key
from uploads.object_store import open_object, save_bytes
from uploads.purposes import MEDIUM_MAX, THUMBNAIL_MAX, WEBP_QUALITY

logger = logging.getLogger(__name__)

# Bound pathological images (decompression bombs) below Pillow's default.
MAX_IMAGE_PIXELS = 20_000_000

VARIANT_SPECS = (
    ("thumbnail", THUMBNAIL_MAX),
    ("medium", MEDIUM_MAX),
    ("optimized", None),
)

_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


def decode_image(file_obj, *, expected_mime: str | None = None) -> Image.Image:
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        img = Image.open(file_obj)
        img.load()
    except Image.DecompressionBombError as exc:
        raise ValueError("Image exceeds maximum pixel count.") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous

    actual_mime = _FORMAT_TO_MIME.get((img.format or "").upper())
    if expected_mime and actual_mime and actual_mime != expected_mime:
        raise ValueError("Decoded image format does not match the declared MIME type.")

    if img.mode == "P":
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    return img


def _to_webp_bytes(img: Image.Image, *, max_dimension: int) -> bytes:
    clone = img.copy()
    clone.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    buffer = io.BytesIO()
    clone.save(buffer, format="WEBP", quality=WEBP_QUALITY)
    return buffer.getvalue()


def process_asset_image(asset, *, max_dimension: int) -> dict:
    with open_object(asset.storage_key) as fh:
        img = decode_image(fh, expected_mime=asset.mime_type)

    variants = {}
    for name, cap in VARIANT_SPECS:
        dim = cap if cap is not None else max_dimension
        payload = _to_webp_bytes(img, max_dimension=dim)
        key = variant_storage_key(asset.storage_key, name)
        save_bytes(key, ContentFile(payload), content_type="image/webp")
        variants[name] = key
    return variants
