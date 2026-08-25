import re
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.deconstruct import deconstructible

from core.models import WebPImageMixin
from core.utils.slug import assign_unique_branch_slug, assign_unique_slug

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
TAG_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "gif"]


@deconstructible
class UniqueFilePath:
    def __init__(self, subdir):
        self.subdir = subdir

    def __call__(self, instance, filename):
        ext = filename.split(".")[-1]
        return f"{self.subdir}/{uuid.uuid4().hex}.{ext}"


class Tag(models.Model):
    """
    Branch-scoped labels for menu items (dietary filters, promotions, etc.).
    Each branch manages its own independent tag catalog.
    """

    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.CASCADE,
        related_name="tags",
    )
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=60, blank=True)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=16,
        blank=True,
        help_text="Optional emoji shown in storefront filters.",
    )
    image = models.ImageField(
        upload_to=UniqueFilePath("menu_tags"),
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=TAG_IMAGE_EXTENSIONS)],
    )
    color = models.CharField(
        max_length=7,
        blank=True,
        help_text="Optional HEX color, e.g. #2ecc71",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive tags are hidden from public storefront endpoints.",
    )
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.color and not HEX_COLOR_PATTERN.match(self.color):
            raise ValidationError({"color": "Color must be a valid HEX value like #2ecc71."})
        if self.icon and len(self.icon) > 16:
            raise ValidationError({"icon": "Icon must be at most 16 characters."})

    def save(self, *args, **kwargs):
        if self.branch_id:
            assign_unique_branch_slug(self, Tag)
        else:
            assign_unique_slug(self, Tag)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.branch_id} - {self.name}"

    class Meta:
        db_table = "menu_tag"
        ordering = ["display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="menu_tag_unique_name_per_branch",
            ),
            models.UniqueConstraint(
                fields=["branch", "slug"],
                name="menu_tag_unique_slug_per_branch",
            ),
        ]


class MenuItem(WebPImageMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.CASCADE,
        related_name="items",
    )

    category = models.ForeignKey(
        "menu.MenuCategory",
        on_delete=models.CASCADE,
        related_name="items",
    )

    name = models.CharField(max_length=255)

    slug = models.SlugField(max_length=280, unique=True, blank=True)

    description = models.TextField(
        blank=True
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    discount = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Discount percentage or amount, depending on project logic",
    )

    image = models.ImageField(
        upload_to=UniqueFilePath("menu_items"),
        blank=True,
        null=True,
    )

    calories = models.PositiveIntegerField(null=True, blank=True)

    preparation_time = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Preparation time in minutes",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Publishing flag — inactive items are hidden from public APIs.",
    )

    available = models.BooleanField(
        default=True,
        help_text="Ordering flag — unavailable items remain visible but cannot be ordered.",
    )

    is_popular = models.BooleanField(default=False)

    is_featured = models.BooleanField(default=False)

    tags = models.ManyToManyField(
        Tag, blank=True, related_name="items"
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Soft-delete timestamp. Set when the item is removed without hard deletion.",
    )

    def save(self, *args, **kwargs):
        assign_unique_slug(self, MenuItem)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "menu_item"


class Extra(models.Model):
    """
    A selectable modifier belonging to a Branch and exactly one ExtraGroup.
    Example: Small, Medium, Large (under a "Drink Size" group).
    The owner creates it once; items receive extras via ExtraGroup assignment.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.CASCADE,
        related_name="extras",
    )
    group = models.ForeignKey(
        "menu.ExtraGroup",
        on_delete=models.CASCADE,
        related_name="extras",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Default price. Can be overridden per item.",
    )
    available = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.branch} - {self.name}"

    class Meta:
        db_table = "menu_extra"
        ordering = ["order"]


class MenuItemExtra(models.Model):
    """
    Through model between MenuItem and Extra.
    Allows overriding an extra's price for a specific item,
    or falling back to the Extra's default price if not overridden.
    """
    item = models.ForeignKey(
        MenuItem,
        on_delete=models.CASCADE,
        related_name="item_extras",
    )
    extra = models.ForeignKey(
        Extra,
        on_delete=models.CASCADE,
        related_name="item_links",
    )
    price_override = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="If left empty, the Extra's default price is used",
    )

    @property
    def price(self):
        return self.price_override if self.price_override is not None else self.extra.price

    @property
    def name(self):
        return self.extra.name

    @property
    def available(self):
        return self.extra.available

    def __str__(self):
        return f"{self.item.name} - {self.extra.name}"

    class Meta:
        db_table = "menu_item_extra"
        unique_together = ("item", "extra")


class MenuItemExtraGroup(models.Model):
    """
    Through model between MenuItem and ExtraGroup.

    Items are assigned ExtraGroups (not individual Extras). The BLL
    materializes MenuItemExtra links from the extras contained in
    assigned groups so existing Order validation keeps working.
    """

    item = models.ForeignKey(
        MenuItem,
        on_delete=models.CASCADE,
        related_name="item_extra_groups",
    )
    extra_group = models.ForeignKey(
        "menu.ExtraGroup",
        on_delete=models.CASCADE,
        related_name="item_links",
    )

    def __str__(self):
        return f"{self.item.name} - {self.extra_group.name}"

    class Meta:
        db_table = "menu_item_extra_group"
        unique_together = ("item", "extra_group")