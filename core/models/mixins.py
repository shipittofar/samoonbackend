# core/models/mixins.py
from django.db import models

from core.utils.image import process_image_to_webp


class WebPImageMixin(models.Model):
    """
    Abstract mixin that converts every ImageField on the model to WebP
    on save() to reduce file size and improve page load times.
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
            process_image_to_webp(getattr(self, field.name))
        super().save(*args, **kwargs)