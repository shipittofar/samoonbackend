# core/models/mixins.py
from django.db import models

from core.utils.image import process_image_to_webp


class WebPImageMixin(models.Model):
    """
    Abstract mixin for models with an `image` field. Automatically
    converts uploaded images to WebP format on save() to reduce file
    size and improve page load times.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        process_image_to_webp(self.image)
        super().save(*args, **kwargs)