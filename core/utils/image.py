import io

from PIL import Image
from django.core.files.base import ContentFile
from django.db.models.fields.files import FieldFile

WEBP_QUALITY = 80
MAX_DIMENSION = 1600


def process_image_to_webp(
    image_field: FieldFile,
    quality: int = WEBP_QUALITY,
    max_dimension: int = MAX_DIMENSION,
) -> None:
    """
    Convert an image field's file to WebP format in place, resizing it if
    it exceeds max_dimension on its longest side. Original bytes uploaded
    by the client are never written to storage; only the processed WebP
    version is persisted.

    Always enforces max_dimension, including already-WebP uploads.
    Skip only happens at the mixin layer for already-committed storage keys.
    """
    if not image_field or not image_field.name:
        return

    image_field.open()
    img = Image.open(image_field)
    img.load()  # force read before the underlying file handle is touched again

    # Always bound dimensions, including already-WebP uploads.
    if img.mode == "P":
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    # Only shrinks images larger than max_dimension, never upscales.
    img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="WEBP", quality=quality)
    buffer.seek(0)

    original_name = image_field.name.rsplit("/", 1)[-1]
    base_name = original_name.rsplit(".", 1)[0]
    new_filename = f"{base_name}.webp"

    # save=False: only writes the file to storage and updates the field's
    # in-memory name/state. The caller's model.save() persists the DB row.
    image_field.save(new_filename, ContentFile(buffer.read()), save=False)