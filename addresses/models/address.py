import hashlib
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from addresses.domain.address_type import AddressType, display_label
from addresses.domain.verification import VerificationStatus
from addresses.managers import ActiveAddressManager, AllAddressesManager


class AddressVerificationMethod(models.TextChoices):
    NONE = "none", "None"
    SMS = "sms", "SMS"
    MANUAL = "manual", "Manual"


# Backward-compatible alias
AddressLabel = AddressType


class Address(models.Model):
    """
    User address book entry. Soft-deletable; never referenced directly by orders.
    Orders store an immutable OrderDeliveryAddress snapshot instead.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    legacy_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        unique=True,
        help_text="Preserved integer PK from the legacy orders.Address table.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="addresses",
    )

    title = models.CharField(max_length=100)
    address_type = models.CharField(
        max_length=20,
        choices=AddressType.choices,
        default=AddressType.HOME,
    )
    custom_label = models.CharField(max_length=100, blank=True, default="")
    # Legacy field kept in sync with address_type for backward compatibility
    label = models.CharField(max_length=20, blank=True, default="")

    first_name = models.CharField(max_length=64)
    last_name = models.CharField(max_length=64)
    company = models.CharField(max_length=128, blank=True, default="")
    phone = models.CharField(max_length=20)
    country_code = models.CharField(max_length=5)
    country = models.CharField(max_length=2, help_text="ISO 3166-1 alpha-2 country code.")
    province = models.CharField(max_length=100, blank=True, default="")
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=100, blank=True, default="")
    street = models.CharField(max_length=500)
    building_number = models.CharField(max_length=32, blank=True, default="")
    unit = models.CharField(max_length=32, blank=True, default="")
    floor = models.CharField(max_length=32, blank=True, default="")
    postal_code = models.CharField(max_length=20)

    latitude = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    formatted_address = models.TextField(blank=True, default="")
    delivery_notes = models.TextField(blank=True, default="")

    is_default = models.BooleanField(default=False)

    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_addresses",
    )
    verification_method = models.CharField(
        max_length=20,
        choices=AddressVerificationMethod.choices,
        default=AddressVerificationMethod.NONE,
    )
    verification_source = models.CharField(max_length=64, blank=True, default="")

    fingerprint = models.CharField(max_length=64, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveAddressManager()
    all_objects = AllAddressesManager()

    class Meta:
        db_table = "user_address"
        ordering = ["-is_default", "-created_at"]
        indexes = [
            models.Index(fields=["user"], name="user_address_user_idx"),
            models.Index(fields=["user", "is_default"], name="user_address_default_idx"),
            models.Index(fields=["city"], name="user_address_city_idx"),
            models.Index(fields=["postal_code"], name="user_address_postal_idx"),
            models.Index(fields=["title"], name="user_address_title_idx"),
            models.Index(fields=["district"], name="user_address_district_idx"),
            models.Index(fields=["formatted_address"], name="user_address_formatted_idx"),
            models.Index(fields=["deleted_at"], name="user_address_deleted_idx"),
            models.Index(fields=["verification_status"], name="user_address_verif_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True, deleted_at__isnull=True),
                name="unique_active_default_address_per_user",
            ),
            models.UniqueConstraint(
                fields=["user", "fingerprint"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_address_fingerprint_per_user",
            ),
        ]

    def __str__(self):
        return self.formatted_address or f"{self.title} — {self.street}, {self.city}"

    @property
    def type_display(self) -> str:
        return display_label(self.address_type, self.custom_label)

    @staticmethod
    def compute_fingerprint(
        *,
        street: str,
        building_number: str,
        unit: str,
        city: str,
        postal_code: str,
        country: str,
    ) -> str:
        normalized = "|".join(
            part.strip().lower()
            for part in (street, building_number, unit, city, postal_code, country)
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def refresh_fingerprint(self) -> None:
        self.fingerprint = self.compute_fingerprint(
            street=self.street,
            building_number=self.building_number,
            unit=self.unit,
            city=self.city,
            postal_code=self.postal_code,
            country=self.country,
        )

    def save(self, *args, **kwargs):
        self.label = self.address_type
        self.refresh_fingerprint()
        super().save(*args, **kwargs)


class AddressAuditLog(models.Model):
    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTION_RESTORE = "restore"
    ACTION_SET_DEFAULT = "set_default"
    ACTION_VERIFICATION_CHANGE = "verification_change"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name="audit_logs")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="address_audit_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="address_audit_actions",
    )
    action = models.CharField(max_length=32)
    changed_fields = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "address_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["address"], name="addr_audit_address_idx"),
            models.Index(fields=["user"], name="addr_audit_user_idx"),
            models.Index(fields=["action"], name="addr_audit_action_idx"),
            models.Index(fields=["created_at"], name="addr_audit_created_idx"),
        ]
