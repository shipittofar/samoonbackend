from django.db import models


class UploadAssetStatus(models.TextChoices):
    INITIATED = "initiated", "Initiated"
    UPLOADED = "uploaded", "Uploaded"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    ATTACHED = "attached", "Attached"
    FAILED = "failed", "Failed"
    EXPIRED = "expired", "Expired"
    DETACHED = "detached", "Detached"


ALLOWED_TRANSITIONS = {
    UploadAssetStatus.INITIATED: {
        UploadAssetStatus.UPLOADED,
        UploadAssetStatus.FAILED,
        UploadAssetStatus.EXPIRED,
    },
    UploadAssetStatus.UPLOADED: {
        UploadAssetStatus.PROCESSING,
        UploadAssetStatus.FAILED,
        UploadAssetStatus.EXPIRED,
    },
    UploadAssetStatus.PROCESSING: {
        UploadAssetStatus.READY,
        UploadAssetStatus.FAILED,
        UploadAssetStatus.EXPIRED,
    },
    UploadAssetStatus.READY: {
        UploadAssetStatus.ATTACHED,
        UploadAssetStatus.EXPIRED,
        UploadAssetStatus.DETACHED,
        UploadAssetStatus.FAILED,
    },
    UploadAssetStatus.ATTACHED: {
        UploadAssetStatus.DETACHED,
    },
    UploadAssetStatus.FAILED: {
        UploadAssetStatus.UPLOADED,
        UploadAssetStatus.EXPIRED,
    },
    UploadAssetStatus.EXPIRED: set(),
    UploadAssetStatus.DETACHED: set(),
}

IDEMPOTENT_COMPLETE_STATUSES = {
    UploadAssetStatus.UPLOADED,
    UploadAssetStatus.PROCESSING,
    UploadAssetStatus.READY,
    UploadAssetStatus.ATTACHED,
}

UNATTACHED_EXPIRE_STATUSES = {
    UploadAssetStatus.INITIATED,
    UploadAssetStatus.UPLOADED,
    UploadAssetStatus.PROCESSING,
    UploadAssetStatus.READY,
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())
