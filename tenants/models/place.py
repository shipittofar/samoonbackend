from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.utils.slug import assign_unique_slug
from core.models import WebPImageMixin


class TenantStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    CLOSED = "closed", "Closed"


from tenants.constants.business_type import BusinessType
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_tenants",
        help_text="The primary owner of this tenant in the system",
    )

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=100, blank=True,)

    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)

    city = models.CharField(max_length=100, blank=True)

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    tax_percentage = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Tax percentage applied to prices (e.g. 9 for 9%)",
    )

    image = models.ImageField(
        upload_to="tenant_images/",
        null=True,
        blank=True,
    )

    business_types = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=20,
        choices=TenantStatus.choices,
        default=TenantStatus.ACTIVE,
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Quick active/inactive toggle for the tenant (independent of status)",
    )

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        assign_unique_slug(self, Tenant)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

    class Meta:
        db_table = "tenant"
        indexes = [
            models.Index(fields=["owner"]),
            models.Index(fields=["status", "is_active"]),
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

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="working_hours",
    )

    day = models.PositiveSmallIntegerField(choices=Weekday.choices)

    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)

    # If True, the tenant is closed all day regardless of open_time/close_time
    is_closed = models.BooleanField(default=False)

    class Meta:
        db_table = "tenant_working_hour"
        unique_together = ("tenant", "day")
        ordering = ["day"]

    def __str__(self) -> str:
        return f"{self.tenant.name} - {self.get_day_display()}"