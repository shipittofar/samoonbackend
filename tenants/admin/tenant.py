# apps/tenants/admin.py
from django import forms
from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from core.exceptions import TenantNotFoundException
from tenants.models import Owner, Tenant, Branch, WorkingHour
from tenants.services.tenant_bll import TenantBusinessLogicLayer
from tenants.settings_cleanup import (
    TenantSettingsContractError,
    project_owner_tenant_settings,
    replace_canonical_tenant_settings,
)

MAX_WORKING_HOURS_PER_BRANCH = 7

TENANT_SETTINGS_HELP = _(
    "Canonical Tenant.settings JSON: theme, featureFlags, addressCapabilities, "
    "marketplace listing metadata, contactEmail, contactPhone, "
    "notificationMatrix. featureFlags is an open UI/rollout map — not RBAC "
    "and not Branch capabilities. addressCapabilities is an open boolean overlay. "
    "Do not store Branch locale, checkout, hours, contact, Website Builder, or "
    "computed marketplace fields. Legacy unknown keys are not shown and are "
    "preserved on save."
)


class TenantAdminForm(forms.ModelForm):
    """Raw JSON editor bounded by the Phase 5B/5C Tenant.settings contract."""

    class Meta:
        model = Tenant
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        settings_field = self.fields.get("settings")
        if settings_field is None:
            return
        settings_field.help_text = TENANT_SETTINGS_HELP
        settings_field.label = _("Settings (canonical JSON)")
        if self.instance and self.instance.pk and not self.is_bound:
            self.initial["settings"] = project_owner_tenant_settings(
                self.instance.settings
            )

    def clean_settings(self):
        value = self.cleaned_data.get("settings")
        if value in (None, ""):
            value = {}
        if not isinstance(value, dict):
            raise forms.ValidationError(_("settings must be a JSON object."))
        try:
            return replace_canonical_tenant_settings(
                getattr(self.instance, "settings", None) or {},
                value,
            )
        except TenantSettingsContractError as exc:
            raise forms.ValidationError(str(exc)) from exc

MAX_WORKING_HOURS_PER_BRANCH = 7


class WorkingHourForm(forms.ModelForm):
    """
    Enforces the "at most 7 WorkingHour rows per Branch" rule. Used both by
    the standalone WorkingHourAdmin and by WorkingHourInline, since the
    inline's `max_num` alone only limits the inline UI — someone could still
    add an 8th row via WorkingHourAdmin's own add page.
    """

    class Meta:
        model = WorkingHour
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        branch = cleaned_data.get("branch")
        if branch is None or branch.pk is None:
            return cleaned_data

        existing = WorkingHour.objects.filter(branch_id=branch.pk)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.count() >= MAX_WORKING_HOURS_PER_BRANCH:
            raise forms.ValidationError(
                _("A branch can have at most %(max)d working hour entries.")
                % {"max": MAX_WORKING_HOURS_PER_BRANCH}
            )
        return cleaned_data


class BranchInline(admin.TabularInline):
    model = Branch
    extra = 0
    fields = ("name", "type", "city", "status", "is_active", "slug")
    readonly_fields = ("slug",)
    show_change_link = True


class WorkingHourInline(admin.TabularInline):
    model = WorkingHour
    form = WorkingHourForm
    extra = 0
    max_num = MAX_WORKING_HOURS_PER_BRANCH
    fields = ("day", "open_time", "close_time", "is_closed")
    ordering = ("day",)


@admin.register(Owner)
class OwnerAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "tenant_count", "created_at")
    search_fields = ("user__phone_number", "user__email",
                     "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)
    list_select_related = ("user",)

    @admin.display(description=_("Tenants"))
    def tenant_count(self, obj):
        return obj.tenants.count()


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    """
    Admin delete is BLL deactivation (status=inactive), not Model.delete().

    NestedObjects would follow Tenant → StaffMembership CASCADE →
    StaffAssignment CASCADE and require delete_staffassignment. Assignments
    are revoke-only history; tenant_bll.delete_tenant inactivates the tenant
    and soft-removes memberships so assignment rows stay in place.
    """

    form = TenantAdminForm
    list_display = (
        "name",
        "owner",
        "business_types",
        "status",
        "is_active",
        "branch_count",
        "tax_percentage",
        "service_charge_percentage",
        "created_at",
    )
    list_filter = ("status", "is_active")
    search_fields = (
        "name", "slug", "owner__user__phone_number", "owner__user__email")
    autocomplete_fields = ("owner",)
    readonly_fields = ("slug", "created_at", "updated_at")
    inlines = (BranchInline,)
    fieldsets = (
        (None, {"fields": ("owner", "name", "slug", "description", "business_types", "status", "is_active")}),
        (_("Business settings"), {
         "fields": ("tax_percentage", "service_charge_percentage", "image",
                    "discover_avatar", "discover_cover", "hero_image")}),
        (_("Tenant settings"), {
            "fields": ("settings",),
            "description": TENANT_SETTINGS_HELP,
        }),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )

    actions = ["deactivate_selected_tenants"]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Branches"))
    def branch_count(self, obj):
        return obj.branches.count()

    def get_deleted_objects(self, objs, request):
        # Deactivate does not physically delete related StaffAssignment history.
        deleted_objects = [str(obj) for obj in objs]
        model_count = {Tenant._meta.verbose_name: len(list(objs))}
        perms_needed = set()
        protected = []
        return deleted_objects, model_count, perms_needed, protected

    def delete_model(self, request, obj):
        self._soft_remove_tenant(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self._soft_remove_tenant(request, obj)

    @admin.action(description=_("Deactivate selected tenants"))
    def deactivate_selected_tenants(self, request, queryset):
        for obj in queryset:
            self._soft_remove_tenant(request, obj)

    def _soft_remove_tenant(self, request, obj):
        try:
            TenantBusinessLogicLayer.delete_tenant(
                user=request.user,
                tenant_id=obj.id,
            )
        except TenantNotFoundException:
            self.message_user(
                request,
                f"Skipped missing tenant {obj}.",
                level=messages.INFO,
            )

    def save_model(self, request, obj, form, change):
        """
        Route owner changes through the canonical transfer BLL so Admin
        cannot bypass workspace cleanup / audit / cache invalidation.
        """
        owner_changed = (
            change
            and form is not None
            and "owner" in getattr(form, "changed_data", [])
        )
        new_owner_user_id = obj.owner.user_id if owner_changed else None

        if owner_changed:
            # Persist non-owner field edits against the current owner first.
            obj.owner_id = (
                Tenant.objects.only("owner_id").get(pk=obj.pk).owner_id
            )

        super().save_model(request, obj, form, change)

        if owner_changed:
            from tenants.services.place_bll import (
                TenantBusinessLogicLayer as PlaceTenantBLL,
            )

            PlaceTenantBLL.transfer_ownership(
                tenant_id=obj.pk,
                new_owner_user_id=new_owner_user_id,
                actor_id=getattr(request.user, "id", None),
            )
            obj.refresh_from_db()


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "tenant",
        "type",
        "city",
        "status",
        "is_active",
        "ordering_enabled",
        "delivery_enabled",
        "marketplace_visible",
        "is_default",
        "created_at",
    )
    list_filter = (
        "status", "is_active", "type", "city",
        "ordering_enabled", "delivery_enabled", "pickup_enabled",
        "marketplace_visible",
    )
    search_fields = (
        "name",
        "slug",
        "tenant__name",
        "address",
        "city",
        "email",
        "manager__phone_number",
        "manager__email",
    )
    autocomplete_fields = ("tenant", "manager")
    readonly_fields = ("slug", "created_at", "updated_at", "location_verified_at")
    inlines = (WorkingHourInline,)
    fieldsets = (
        (None, {
            "fields": (
                "tenant", "name", "slug", "description", "type",
                "status", "is_active", "is_default", "manager",
            )
        }),
        (_("Contact"), {"fields": ("phone", "email", "website")}),
        (_("Location"), {"fields": ("address", "city",
         "country", "postal_code", "latitude", "longitude",
         "service_area", "location_verified_at")}),
        (_("Media"), {"fields": ("image", "cover_image", "hero_image")}),
        (_("Locale"), {"fields": ("time_zone", "currency", "language")}),
        (_("Checkout"), {
            "fields": (
                "ordering_enabled",
                "delivery_enabled",
                "pickup_enabled",
                "table_ordering_enabled",
                "default_order_type",
            ),
        }),
        (_("Delivery"), {
            "fields": (
                "delivery_radius_km",
                "minimum_order_amount",
                "same_day_delivery_enabled",
                "scheduled_delivery_enabled",
                "contactless_delivery_enabled",
                "cash_on_delivery_enabled",
            ),
        }),
        (_("Payments"), {
            "fields": (
                "cash_payment_enabled",
                "card_payment_enabled",
                "online_payment_enabled",
                "wallet_payment_enabled",
                "default_payment_method",
            ),
        }),
        (_("Marketplace"), {"fields": ("marketplace_visible", "cuisines", "amenities")}),
        (_("Reservation"), {"fields": ("reservations_enabled", "max_capacity")}),
        (_("Advanced"), {"fields": ("settings", "metadata")}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )
    actions = ["deactivate_selected_branches"]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description=_("Deactivate selected branches"))
    def deactivate_selected_branches(self, request, queryset):
        from tenants.services.tenant_bll import BranchBusinessLogicLayer

        for branch in queryset:
            BranchBusinessLogicLayer.delete_branch(
                user=request.user,
                tenant_id=branch.tenant_id,
                branch_id=branch.id,
            )


@admin.register(WorkingHour)
class WorkingHourAdmin(admin.ModelAdmin):
    form = WorkingHourForm
    list_display = ("branch", "day", "open_time", "close_time", "is_closed")
    list_filter = ("day", "is_closed")
    search_fields = ("branch__name", "branch__tenant__name")
    autocomplete_fields = ("branch",)
    ordering = ("branch", "day")
