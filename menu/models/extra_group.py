import uuid

from django.db import models


class ExtraGroupSelectionType(models.TextChoices):
    SINGLE = "single", "Single"
    MULTIPLE = "multiple", "Multiple"


class ExtraGroup(models.Model):
    """
    A logical container for Extras (modifiers) that defines selection rules.

    ExtraGroup is NOT selectable and has no price. It groups Extras and
    controls how customers may choose among them: whether selection is required,
    single vs. multiple choice, and min/max selection counts.

    Examples: "Drink Size", "Choose your sauce", "Extra toppings".
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.CASCADE,
        related_name="extra_groups",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    selection_type = models.CharField(
        max_length=10,
        choices=ExtraGroupSelectionType.choices,
        default=ExtraGroupSelectionType.MULTIPLE,
    )
    required = models.BooleanField(default=False)
    min_selection = models.PositiveIntegerField(default=0)
    max_selection = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.branch} - {self.name}"

    class Meta:
        db_table = "menu_extra_group"
        ordering = ["order"]
