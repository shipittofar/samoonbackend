from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from uploads.state import UploadAssetStatus


class UploadAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="upload_assets",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="upload_assets",
    )
    purpose = models.CharField(max_length=64, db_index=True)
    original_filename = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=128)
    byte_size = models.PositiveBigIntegerField()
    checksum = models.CharField(max_length=128, blank=True)
    storage_key = models.CharField(max_length=512, unique=True)
    variant_keys = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=UploadAssetStatus.choices,
        default=UploadAssetStatus.INITIATED,
        db_index=True,
    )
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    attached_to_type = models.CharField(max_length=64, blank=True)
    attached_to_id = models.CharField(max_length=64, blank=True)
    processing_attempts = models.PositiveSmallIntegerField(default=0)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.TextField(blank=True)
    expires_at = models.DateTimeField(db_index=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    detached_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "upload_asset"
        indexes = [
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["tenant", "purpose", "status"]),
            models.Index(fields=["created_by", "purpose", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "idempotency_key"],
                name="upload_asset_idempotency_per_user",
                condition=models.Q(idempotency_key__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        return f"UploadAsset({self.id} {self.purpose} {self.status})"

    @property
    def public_key(self) -> str:
        variants = self.variant_keys or {}
        return variants.get("optimized") or self.storage_key

    def public_url(self) -> str | None:
        from django.core.files.storage import default_storage

        key = self.public_key
        if not key:
            return None
        try:
            return default_storage.url(key)
        except Exception:
            return None

    def is_expired(self) -> bool:
        return bool(self.expires_at and timezone.now() >= self.expires_at)
