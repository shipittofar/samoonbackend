import uuid

from django.db import models


class QrEntityType(models.TextChoices):
    TENANT = "tenant", "Tenant"
    BRANCH = "branch", "Branch"


class QrDestinationType(models.TextChoices):
    TENANT = "tenant", "Tenant"
    BRANCH = "branch", "Branch"
    MENU = "menu", "Menu"
    RESERVATION = "reservation", "Reservation"


class QrCode(models.Model):
    """Stable public identifier for printed QR codes.

    The ``code`` is what is encoded in the QR image (``/qr/<code>``).
    Destination URLs are resolved from live tenant/branch slugs and
    ``destination_type`` so reprints are not required when slugs change.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=32, unique=True)
    entity_type = models.CharField(max_length=20, choices=QrEntityType.choices)
    entity_id = models.UUIDField()
    destination_type = models.CharField(
        max_length=20,
        choices=QrDestinationType.choices,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "qr_code"
        indexes = [
            models.Index(
                fields=["entity_type", "entity_id"],
                name="qr_code_entity__idx",
            ),
            models.Index(fields=["is_active"], name="qr_code_is_activ_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "entity_id"],
                condition=models.Q(is_active=True),
                name="unique_active_qr_per_entity",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.code}"
