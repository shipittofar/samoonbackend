# access/admin.py
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from access.models import (
    AssignmentStatus,
    Permission,
    Role,
    RolePermission,
    StaffAssignment,
    StaffMembership,
)
from access.services.assignment_bll import assignment_bll
from access.services.membership_bll import membership_service
from access.authorization.admin_role_protection import filter_roles_queryset_for_viewer
from core.exceptions import StaffMembershipAlreadyRemovedException
from tenants.models import Branch

_STAFF_ASSIGNMENT_WRITE_BLOCKED = (
    "StaffAssignment writes are disabled on the membership inline. "
    "Use the Staff Assignment admin page (assignment_bll-backed)."
)


def _drf_validation_to_django(exc: DRFValidationError) -> DjangoValidationError:
    detail = exc.detail
    if isinstance(detail, dict):
        messages_dict = {
            key: [str(item) for item in (value if isinstance(value, list) else [value])]
            for key, value in detail.items()
        }
        return DjangoValidationError(messages_dict)
    if isinstance(detail, list):
        return DjangoValidationError([str(item) for item in detail])
    return DjangoValidationError(str(detail))


class StaffAssignmentAdminForm(forms.ModelForm):
    """Admin form that collects assignment fields; persistence is owned by assignment_bll."""

    locations = forms.ModelMultipleChoiceField(
        queryset=Branch.objects.none(),
        required=False,
        widget=FilteredSelectMultiple("locations", is_stacked=False),
        help_text=(
            "Leave empty when All locations is checked. "
            "Otherwise select one or more branches of the membership's tenant."
        ),
    )

    class Meta:
        model = StaffAssignment
        fields = (
            "membership",
            "role",
            "all_locations",
            "mode",
            "valid_from",
            "valid_until",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "membership" in self.fields:
            self.fields["membership"].queryset = StaffMembership.objects.select_related(
                "user", "tenant"
            ).order_by("tenant__name", "user__email")

        membership = self._resolve_membership_for_queryset()
        if "locations" in self.fields:
            if membership is not None:
                self.fields["locations"].queryset = Branch.objects.filter(
                    tenant_id=membership.tenant_id
                ).order_by("name")
            else:
                self.fields["locations"].queryset = Branch.objects.none()

            if self.instance and not self.instance._state.adding and not self.is_bound:
                self.fields["locations"].initial = list(
                    self.instance.locations.values_list("branch_id", flat=True)
                )

        if (
            "membership" in self.fields
            and self.instance
            and not self.instance._state.adding
        ):
            # Membership is immutable after create (BLL update has no membership_id).
            self.fields["membership"].disabled = True

        if (
            self.instance
            and not self.instance._state.adding
            and self.instance.status == AssignmentStatus.REVOKED
        ):
            for field in self.fields.values():
                field.disabled = True

    def _resolve_membership_for_queryset(self):
        raw = None
        if self.is_bound and "membership" in self.fields:
            raw = self.data.get(self.add_prefix("membership"))
        elif self.instance and not self.instance._state.adding and self.instance.membership_id:
            return self.instance.membership

        if not raw and self.is_bound and self.instance and not self.instance._state.adding:
            # Membership is often readonly on change, so it is absent from POST.
            return self.instance.membership

        if not raw:
            return None
        return (
            StaffMembership.objects.select_related("tenant")
            .filter(pk=raw)
            .first()
        )

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if role is not None and role.slug == "owner":
            raise DjangoValidationError("StaffAssignment.role cannot be 'owner'.")
        return role

    def clean(self):
        cleaned = super().clean()

        if (
            self.instance
            and not self.instance._state.adding
            and self.instance.status == AssignmentStatus.REVOKED
        ):
            raise DjangoValidationError("Cannot update a revoked assignment.")

        membership = cleaned.get("membership")
        if membership is None and self.instance and not self.instance._state.adding:
            membership = self.instance.membership
            cleaned["membership"] = membership

        all_locations = cleaned.get("all_locations")
        locations = list(cleaned.get("locations") or [])

        if all_locations and locations:
            self.add_error(
                "locations",
                "Must be empty when all_locations is true.",
            )
        if all_locations is False and not locations:
            self.add_error(
                "locations",
                "At least one location is required when all_locations is false.",
            )

        if membership is not None and locations:
            invalid = [branch for branch in locations if branch.tenant_id != membership.tenant_id]
            if invalid:
                self.add_error(
                    "locations",
                    "All locations must belong to the same tenant as the membership.",
                )

        return cleaned


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 1
    autocomplete_fields = ["permission"]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "system_role", "created_at"]
    list_filter = ["system_role"]
    search_fields = ["name", "slug"]
    ordering = ["slug"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [RolePermissionInline]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ["slug", "resource", "action"]
    list_filter = ["resource"]
    search_fields = ["slug", "resource", "action"]
    ordering = ["resource", "action"]
    readonly_fields = ["id"]


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ["role", "permission"]
    list_filter = ["role"]
    autocomplete_fields = ["role", "permission"]
    search_fields = ["role__name", "permission__slug"]


class StaffAssignmentInline(admin.TabularInline):
    """Read-only visibility of assignments on the membership change page."""

    model = StaffAssignment
    fk_name = "membership"
    extra = 0
    can_delete = False
    show_change_link = True
    fields = [
        "role",
        "all_locations",
        "status",
        "mode",
        "created_at",
        "updated_at",
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # Render existing rows read-only; persistence is blocked on the parent admin.
        return True


@admin.register(StaffMembership)
class StaffMembershipAdmin(admin.ModelAdmin):
    """
    Membership removal is BLL-owned (status=removed + revoke non-terminal
    assignments). StaffAssignment.membership is PROTECT so accidental physical
    deletion cannot cascade assignment history. Named action replaces Delete UI.
    """

    list_display = ["user", "tenant", "status", "invited_by", "joined_at", "created_at"]
    list_filter = ["status", "tenant"]
    search_fields = ["user__phone_number", "user__email", "tenant__name"]
    autocomplete_fields = ["user", "tenant", "invited_by"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [StaffAssignmentInline]
    actions = ["remove_selected_memberships"]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Remove selected memberships")
    def remove_selected_memberships(self, request, queryset):
        for obj in queryset:
            self._soft_remove_membership(request, obj)

    def get_deleted_objects(self, objs, request):
        # Soft-remove does not delete related StaffAssignment / location rows.
        deleted_objects = [str(obj) for obj in objs]
        model_count = {StaffMembership._meta.verbose_name: len(list(objs))}
        perms_needed = set()
        protected = []
        return deleted_objects, model_count, perms_needed, protected

    def delete_model(self, request, obj):
        self._soft_remove_membership(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self._soft_remove_membership(request, obj)

    def _soft_remove_membership(self, request, obj):
        try:
            membership_service.remove_membership(
                tenant_id=obj.tenant_id,
                membership_id=obj.id,
                actor_id=getattr(request.user, "id", None),
            )
        except StaffMembershipAlreadyRemovedException:
            self.message_user(
                request,
                f"Skipped already-removed membership {obj}.",
                level=messages.INFO,
            )

    def save_formset(self, request, form, formset, change):
        if formset.model is StaffAssignment:
            if formset.deleted_forms or formset.has_changed():
                raise PermissionDenied(_STAFF_ASSIGNMENT_WRITE_BLOCKED)
            # Run a no-op save so Django admin can read new/changed/deleted tracking
            # attributes populated only inside BaseModelFormSet.save().
            formset.save()
            return
        super().save_formset(request, form, formset, change)


@admin.register(StaffAssignment)
class StaffAssignmentAdmin(admin.ModelAdmin):
    """
    Assignment mutations go exclusively through assignment_bll.
    Hard delete is disabled; use the Revoke action instead.
    """

    form = StaffAssignmentAdminForm
    list_display = [
        "membership",
        "role",
        "all_locations",
        "status",
        "mode",
        "created_at",
    ]
    list_filter = ["role", "all_locations", "status", "mode"]
    search_fields = [
        "membership__user__phone_number",
        "membership__user__email",
        "membership__tenant__name",
        "role__name",
    ]
    autocomplete_fields = ["membership"]
    readonly_fields = [
        "id",
        "status",
        "granted_by",
        "granted_at",
        "revoked_by",
        "revoked_at",
        "created_at",
        "updated_at",
    ]
    fields = [
        "membership",
        "role",
        "all_locations",
        "locations",
        "mode",
        "valid_from",
        "valid_until",
        "id",
        "status",
        "granted_by",
        "granted_at",
        "revoked_by",
        "revoked_at",
        "created_at",
        "updated_at",
    ]
    actions = ["revoke_selected_assignments"]
    list_select_related = ("membership", "membership__user", "membership__tenant", "role")

    class Media:
        # FilteredSelectMultiple requires admin's SelectFilter JS/CSS.
        js = ["admin/js/jquery.init.js", "admin/js/SelectBox.js", "admin/js/SelectFilter2.js"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "role":
            kwargs["queryset"] = filter_roles_queryset_for_viewer(
                Role.objects.exclude(slug="owner").order_by("slug"),
                request.user,
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.readonly_fields)
        if obj is not None:
            readonly.append("membership")
        if obj is not None and obj.status == AssignmentStatus.REVOKED:
            readonly.extend(
                [
                    "role",
                    "all_locations",
                    "mode",
                    "valid_from",
                    "valid_until",
                ]
            )
        return readonly

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        membership = form.cleaned_data.get("membership") or obj.membership
        role = form.cleaned_data.get("role") or obj.role
        all_locations = form.cleaned_data.get("all_locations", obj.all_locations)
        locations = form.cleaned_data.get("locations")
        if locations is None:
            location_ids = list(obj.locations.values_list("branch_id", flat=True))
        else:
            location_ids = [branch.id for branch in locations]
        mode = form.cleaned_data.get("mode", obj.mode)
        valid_from = form.cleaned_data.get("valid_from", obj.valid_from)
        valid_until = form.cleaned_data.get("valid_until", obj.valid_until)

        try:
            if change:
                if obj.status == AssignmentStatus.REVOKED:
                    raise DjangoValidationError("Cannot update a revoked assignment.")
                assignment = assignment_bll.update_assignment(
                    assignment_id=obj.pk,
                    role_id=role.id,
                    branch_ids=location_ids,
                    all_locations=all_locations,
                    mode=mode,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    updated_by_id=request.user.id,
                )
            else:
                assignment = assignment_bll.create_assignment(
                    membership_id=membership.id,
                    role_id=role.id,
                    branch_ids=location_ids,
                    all_locations=all_locations,
                    mode=mode,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    granted_by_id=request.user.id,
                )
        except DRFValidationError as exc:
            raise _drf_validation_to_django(exc) from exc

        # Point Admin at the persisted row without calling obj.save().
        obj.pk = assignment.pk
        obj.id = assignment.id
        for field in (
            "membership_id",
            "role_id",
            "all_locations",
            "mode",
            "status",
            "valid_from",
            "valid_until",
            "granted_by_id",
            "granted_at",
            "revoked_by_id",
            "revoked_at",
        ):
            setattr(obj, field, getattr(assignment, field))

    def delete_model(self, request, obj):
        raise PermissionDenied(
            "Hard delete is disabled. Use the 'Revoke selected assignments' action."
        )

    def delete_queryset(self, request, queryset):
        raise PermissionDenied(
            "Hard delete is disabled. Use the 'Revoke selected assignments' action."
        )

    @admin.action(description="Revoke selected assignments")
    def revoke_selected_assignments(self, request, queryset):
        revoked = 0
        skipped = 0
        for assignment in queryset:
            if assignment.status == AssignmentStatus.REVOKED:
                skipped += 1
                continue
            try:
                assignment_bll.revoke_assignment(
                    assignment_id=assignment.id,
                    revoked_by_id=request.user.id,
                )
                revoked += 1
            except DRFValidationError as exc:
                self.message_user(
                    request,
                    f"Failed to revoke {assignment.id}: {_drf_validation_to_django(exc)}",
                    level=messages.ERROR,
                )
        if revoked:
            self.message_user(
                request,
                f"Revoked {revoked} assignment(s).",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} already-revoked assignment(s).",
                level=messages.INFO,
            )
