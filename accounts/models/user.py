import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from accounts.managers.user_manager import UserManager


class UserRole(models.TextChoices):
    """Read-only label derived from ``is_superuser`` (no column, so it can
    never disagree with it)."""

    CUSTOMER = "customer", "Customer"
    ADMIN = "admin", "Admin"


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    country_code = models.CharField(max_length=5, blank=True, null=True)
    phone_number = models.CharField(max_length=20, unique=True, db_index=True, blank=True, null=True)
    email = models.EmailField(blank=True, null=True, unique=True)

    first_name = models.CharField(max_length=64, blank=True, null=True)
    last_name = models.CharField(max_length=64, blank=True, null=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True, max_length=512)
    avatar_asset = models.ForeignKey(
        "uploads.UploadAsset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # Not identity verification: true once the person confirmed a complete
    # profile (first/last name, phone, email) via POST /api/auth/verify-account/.
    is_verified = models.BooleanField(
        default=False,
        verbose_name="profile confirmed",
        help_text="Set by verify-account once name, phone and email are all present.",
    )

    active_tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    active_branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    # A deleted account gives its phone and email back (so the person can sign
    # up again); the old values are kept here for support and for restoring.
    deleted_phone_number = models.CharField(max_length=20, blank=True, null=True)
    deleted_email = models.EmailField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()
    all_objects = UserManager(include_deleted=True)

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        return self.phone_number or self.email or str(self.id)

    @property
    def role(self) -> str:
        """"admin" for a platform superuser, otherwise "customer"."""
        return UserRole.ADMIN if self.is_superuser else UserRole.CUSTOMER

    @property
    def full_name(self) -> str:
        return f"{self.first_name or ''} {self.last_name or ''}".strip()

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.active_branch_id and not self.active_tenant_id:
            raise ValidationError(
                {"active_branch": "active_branch requires an active_tenant."}
            )
        if (
            self.active_branch_id
            and self.active_tenant_id
            and str(self.active_branch.tenant_id) != str(self.active_tenant_id)
        ):
            raise ValidationError(
                {"active_branch": "active_branch must belong to active_tenant."}
            )