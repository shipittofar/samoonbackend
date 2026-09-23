from django.core.files.uploadedfile import UploadedFile
from django.db import models

from core.utils.image import process_image_to_webp


class WebPImageMixin(models.Model):
    """
    Convert newly uploaded ImageField files to WebP on save().
    Storage-key assignments from UploadAsset are left untouched.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        for field in self._meta.fields:
            if not isinstance(field, models.ImageField):
                continue
            if update_fields is not None and field.name not in update_fields:
                continue
            file = getattr(self, field.name)
            if not file:
                continue
            # FieldFile.file opens storage. Read the already-bound file only.
            # Committed storage keys have no UploadedFile and must not be opened.
            inner = getattr(file, "_file", None)
            if not isinstance(inner, UploadedFile):
                continue
            process_image_to_webp(file)
        super().save(*args, **kwargs)
