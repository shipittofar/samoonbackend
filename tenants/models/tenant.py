# apps/tenants/models.py
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
import uuid

from core.utils.slug import assign_unique_slug
from core.models import WebPImageMixin
from tenants.constants.business_type import validate_business_types
from tenants.checkout_config import default_branch_settings
from tenants.settings_cleanup import strip_phase1_deprecated_tenant_settings


class OwnerStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    PENDING_VERIFICATION = "pending_verification", "Pending Verification"


class Owner(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owner_profile",
    )
    status = models.CharField(
        max_length=30,
        choices=OwnerStatus.choices,
        null=True,
        blank=True,
    )
    plan = models.CharField(max_length=50, null=True, blank=True)
    max_tenants = models.IntegerField(null=True, blank=True)
    billing_customer_id = models.CharField(max_length=100, null=True, blank=True)
    billing_email = models.EmailField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "owner"

    def __str__(self) -> str:
        return self.user.phone_number or self.user.email


class TenantStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    CLOSED = "closed", "Closed"


class Tenant(WebPImageMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        Owner, on_delete=models.PROTECT, related_name="tenants",
        help_text="The owner profile that owns this business",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=100, blank=True)
    description = models.TextField(blank=True)
    tax_percentage = models.DecimalField(
        max_digits=4, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Default tax percentage applied to prices (e.g. 9 for 9%)",
    )
    service_charge_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Service charge percentage applied to dine-in orders (e.g. 10 for 10%)",
    )
    image = models.ImageField(upload_to="tenant_images/", null=True, blank=True)
    discover_avatar = models.ImageField(
        upload_to="tenant_discover_avatars/", null=True, blank=True,
    )
    discover_cover = models.ImageField(
        upload_to="tenant_discover_covers/", null=True, blank=True,
    )
    hero_image = models.ImageField(
        upload_to="tenant_heroes/", null=True, blank=True,
    )
    business_types = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=TenantStatus.choices, default=TenantStatus.INACTIVE)
    is_active = models.BooleanField(
        default=True,
        help_text="Quick active/inactive toggle for the tenant (independent of status)",
    )
    settings = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.business_types is not None:
            self.business_types = validate_business_types(self.business_types)
        self.settings = strip_phase1_deprecated_tenant_settings(self.settings)
        assign_unique_slug(self, Tenant)
        super().save(*args, **kwargs)
        from tenants.services.qr_bll import QrCodeBusinessLogicLayer

        QrCodeBusinessLogicLayer.attach_after_save(self)

    def get_feature_flag(self, flag: str, default=False):
        """JSON accessor for ``settings.featureFlags``.

        Does not consult Owner.plan, RBAC, or Branch capabilities.
        Production authorization must not call this to grant or deny
        permissions; the frontend resolves flags separately for UI/nav.
        """
        feature_flags = (self.settings or {}).get("featureFlags") or {}
        return feature_flags.get(flag, default)

    def __str__(self) -> str:
        return self.name

    class Meta:
        db_table = "tenant"
        indexes = [models.Index(fields=["owner"]), models.Index(fields=["status"])]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="unique_tenant_name_per_owner"),
        ]


class BranchStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    MAINTENANCE = "maintenance", "Maintenance"  # renamed from CLOSED to match frontend contract


class BranchType(models.TextChoices):
    PHYSICAL = "physical", "Physical"
    MOBILE = "mobile", "Mobile"


class BranchOrderType(models.TextChoices):
    DELIVERY = "delivery", "Delivery"
    PICKUP = "pickup", "Pickup"
    DINE_IN = "dine_in", "Dine In"


class BranchPaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    CARD = "card", "Card"
    ONLINE = "online", "Online"
    WALLET = "wallet", "Wallet"


class Branch(WebPImageMixin, models.Model):
    """A physical (or mobile) location of a Tenant."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="branches")

    name = models.CharField(max_length=255, blank=True)
    slug = models.SlugField(unique=True, max_length=100, blank=True)
    description = models.TextField(blank=True)

    type = models.CharField(max_length=20, choices=BranchType.choices, default=BranchType.PHYSICAL)

    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_branches",
        help_text="User responsible for operating this branch",
    )

    # --- contact ---
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    # --- location ---
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    # --- media ---
    image = models.ImageField(upload_to="branch_images/", null=True, blank=True)
    cover_image = models.ImageField(upload_to="branch_covers/", null=True, blank=True)
    hero_image = models.ImageField(upload_to="branch_heroes/", null=True, blank=True)

    # --- locale ---
    time_zone = models.CharField(max_length=64, blank=True, default="UTC")
    currency = models.CharField(max_length=10, blank=True, default="USD")
    language = models.CharField(max_length=10, blank=True, default="en")

    # --- checkout (operational) ---
    ordering_enabled = models.BooleanField(default=True)
    delivery_enabled = models.BooleanField(default=False)
    pickup_enabled = models.BooleanField(default=False)
    table_ordering_enabled = models.BooleanField(default=False)
    default_order_type = models.CharField(
        max_length=32,
        choices=BranchOrderType.choices,
        null=True,
        blank=True,
    )

    delivery_radius_km = models.PositiveIntegerField(null=True, blank=True)
    minimum_order_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    same_day_delivery_enabled = models.BooleanField(default=False)
    scheduled_delivery_enabled = models.BooleanField(default=True)
    contactless_delivery_enabled = models.BooleanField(default=False)
    cash_on_delivery_enabled = models.BooleanField(default=True)

    cash_payment_enabled = models.BooleanField(default=True)
    card_payment_enabled = models.BooleanField(default=True)
    online_payment_enabled = models.BooleanField(default=False)
    wallet_payment_enabled = models.BooleanField(default=False)
    default_payment_method = models.CharField(
        max_length=32,
        choices=BranchPaymentMethod.choices,
        null=True,
        blank=True,
    )

    marketplace_visible = models.BooleanField(default=True)
    reservations_enabled = models.BooleanField(default=False)
    max_capacity = models.PositiveIntegerField(null=True, blank=True)

    cuisines = models.JSONField(default=list, blank=True)
    amenities = models.JSONField(default=list, blank=True)

    # --- extension settings (non-operational JSON only) ---
    settings = models.JSONField(default=default_branch_settings, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=20, choices=BranchStatus.choices, default=BranchStatus.ACTIVE)
    is_active = models.BooleanField(
        default=True,
        help_text="Internal quick toggle; folded into 'status' in API responses",
    )
    is_default = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        assign_unique_slug(self, Branch)
        super().save(*args, **kwargs)
        from tenants.services.qr_bll import QrCodeBusinessLogicLayer

        QrCodeBusinessLogicLayer.attach_after_save(self)

    def __str__(self) -> str:
        return f"{self.tenant.name} - {self.name}" if self.name else self.tenant.name

    class Meta:
        db_table = "branch"
        indexes = [
            models.Index(fields=["tenant"]),
            models.Index(fields=["status", "is_active"]),
            models.Index(fields=["marketplace_visible"]),
        ]


class WorkingHour(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="working_hours")
    day = models.PositiveSmallIntegerField(choices=Weekday.choices)
    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        db_table = "branch_working_hour"
        unique_together = ("branch", "day")
        ordering = ["day"]

    def __str__(self) -> str:
        return f"{self.branch} - {self.get_day_display()}"
