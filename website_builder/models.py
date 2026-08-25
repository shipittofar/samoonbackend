import uuid

from django.db import models

from tenants.models import Branch, Tenant


class WebsiteLayoutStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"


class WebsiteLayout(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="website_layout",
    )
    layout_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=WebsiteLayoutStatus.choices,
        default=WebsiteLayoutStatus.DRAFT,
    )
    last_saved_at = models.DateTimeField(null=True, blank=True)
    last_published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "website_layout"

    def __str__(self) -> str:
        return f"WebsiteLayout({self.tenant_id})"


class BranchWebsiteOverride(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    website_layout = models.ForeignKey(
        WebsiteLayout,
        on_delete=models.CASCADE,
        related_name="branch_overrides",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="website_overrides",
    )
    override_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "branch_website_override"
        constraints = [
            models.UniqueConstraint(
                fields=["website_layout", "branch"],
                name="unique_branch_website_override",
            ),
        ]

    def __str__(self) -> str:
        return f"BranchWebsiteOverride({self.branch_id})"
