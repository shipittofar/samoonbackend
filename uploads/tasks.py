from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from uploads.models import UploadAsset
from uploads.processing import process_asset_image
from uploads.purposes import get_purpose
from uploads.state import UploadAssetStatus, can_transition

logger = logging.getLogger(__name__)

MAX_PROCESS_ATTEMPTS = 3


@shared_task(
    bind=True,
    max_retries=MAX_PROCESS_ATTEMPTS,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def process_upload_asset(self, asset_id: str):
    with transaction.atomic():
        asset = UploadAsset.objects.select_for_update().filter(id=asset_id).first()
        if asset is None:
            return
        if asset.status in {
            UploadAssetStatus.READY,
            UploadAssetStatus.ATTACHED,
            UploadAssetStatus.EXPIRED,
            UploadAssetStatus.DETACHED,
        }:
            return
        if asset.status not in {
            UploadAssetStatus.UPLOADED,
            UploadAssetStatus.PROCESSING,
            UploadAssetStatus.FAILED,
        }:
            return
        if asset.status != UploadAssetStatus.PROCESSING:
            if not can_transition(asset.status, UploadAssetStatus.PROCESSING):
                return
            asset.status = UploadAssetStatus.PROCESSING
        asset.processing_attempts = (asset.processing_attempts or 0) + 1
        asset.save(update_fields=["status", "processing_attempts", "updated_at"])

    try:
        policy = get_purpose(asset.purpose)
        variants = {}
        if policy.require_image:
            variants = process_asset_image(asset, max_dimension=policy.max_dimension)
        with transaction.atomic():
            asset = UploadAsset.objects.select_for_update().get(pk=asset_id)
            if asset.status != UploadAssetStatus.PROCESSING:
                return
            asset.variant_keys = variants
            asset.status = UploadAssetStatus.READY
            asset.processed_at = timezone.now()
            asset.failure_code = ""
            asset.failure_message = ""
            asset.save(
                update_fields=[
                    "variant_keys",
                    "status",
                    "processed_at",
                    "failure_code",
                    "failure_message",
                    "updated_at",
                ]
            )
    except Exception as exc:
        logger.exception("Failed processing upload %s", asset_id)
        retries = self.request.retries
        with transaction.atomic():
            asset = UploadAsset.objects.select_for_update().filter(id=asset_id).first()
            if asset is not None and retries >= MAX_PROCESS_ATTEMPTS:
                asset.status = UploadAssetStatus.FAILED
                asset.failure_code = "processing_failed"
                asset.failure_message = str(exc)[:2000]
                asset.save(
                    update_fields=[
                        "status",
                        "failure_code",
                        "failure_message",
                        "updated_at",
                    ]
                )
                return
        raise


@shared_task
def expire_orphan_uploads():
    from uploads.services.upload_bll import expire_unattached_assets

    return expire_unattached_assets()
