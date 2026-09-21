from __future__ import annotations

import io
import logging

from PIL import Image
from django.core.files.base import ContentFile

from uploads.keys import variant_storage_key
from uploads.object_store import open_object, save_bytes
from uploads.purposes import MEDIUM_MAX, THUMBNAIL_MAX, WEBP_QUALITY

logger = logging.getLogger(__name__)

VARIANT_SPECS = (
    ("thumbnail", THUMBNAIL_MAX),
    ("medium", MEDIUM_MAX),
    ("optimized", None),
)


def decode_image(file_obj) -> Image.Image:
    img = Image.open(file_obj)
    img.load()
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
        img = decode_image(fh)

    variants = {}
    for name, cap in VARIANT_SPECS:
        dim = cap if cap is not None else max_dimension
        payload = _to_webp_bytes(img, max_dimension=dim)
        key = variant_storage_key(asset.storage_key, name)
        save_bytes(key, ContentFile(payload), content_type="image/webp")
        variants[name] = key
    return variants
