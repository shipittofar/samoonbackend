from rest_framework import serializers

from access.authorization.admin_role_protection import (
    assert_role_assignable_by_actor,
    assert_role_slug_assignable,
)
from access.models import AssignmentMode, Role, StaffMembership


class RoleCreateSerializer(serializers.ModelSerializer):
    slug = serializers.CharField(max_length=20)

    class Meta:
        model = Role
        fields = ("slug", "name", "description")

    def validate(self, attrs):
        if self.initial_data.get("system_role"):
            raise serializers.ValidationError(
                {"system_role": "System roles cannot be created through the API."}
            )
        request = self.context.get("request")
        actor = getattr(request, "user", None) if request is not None else None
        if actor is not None:
            assert_role_slug_assignable(slug=attrs["slug"], actor=actor)
        return attrs


class RolePermissionAddSerializer(serializers.Serializer):
    permission_slugs = serializers.ListField(
        child=serializers.CharField(max_length=100), allow_empty=False
    )


class StaffMembershipCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffMembership
        fields = ("user", "status")
        extra_kwargs = {"status": {"required": False}}


class StaffMembershipUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffMembership
        fields = ("status",)
        extra_kwargs = {"status": {"required": True}}


class _StaffAssignmentScopeValidatorMixin:
    def _validate_location_scope(self, *, all_locations: bool, location_ids: list) -> None:
        if all_locations and location_ids:
            raise serializers.ValidationError(
                {"location_ids": "Must be empty when all_locations is true."}
            )
        if not all_locations and not location_ids:
            raise serializers.ValidationError(
                {
                    "location_ids": (
                        "At least one location_id is required when all_locations is false."
                    )
                }
            )


class StaffAssignmentCreateSerializer(
    _StaffAssignmentScopeValidatorMixin, serializers.Serializer
):
    membership_id = serializers.UUIDField()
    role_id = serializers.UUIDField()
    location_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
    )
    all_locations = serializers.BooleanField()
    mode = serializers.ChoiceField(
        choices=AssignmentMode.choices,
        default=AssignmentMode.MANAGE,
        required=False,
    )
    valid_from = serializers.DateTimeField(required=False, allow_null=True)
    valid_until = serializers.DateTimeField(required=False, allow_null=True)

    def validate_membership_id(self, value):
        tenant_id = self.context.get("tenant_id")
        if tenant_id is None:
            return value
        if not StaffMembership.objects.filter(id=value, tenant_id=tenant_id).exists():
            raise serializers.ValidationError(
                "Staff membership not found for this tenant."
            )
        return value

    def validate_role_id(self, value):
        role = Role.objects.filter(id=value).first()
        if role is None:
            raise serializers.ValidationError("Role not found.")
        request = self.context.get("request")
        actor = getattr(request, "user", None) if request is not None else None
        if actor is not None:
            assert_role_assignable_by_actor(role=role, actor=actor)
        return value

    def validate(self, attrs):
        self._validate_location_scope(
            all_locations=attrs["all_locations"],
            location_ids=attrs.get("location_ids", []),
        )
        return attrs


class StaffAssignmentUpdateSerializer(
    _StaffAssignmentScopeValidatorMixin, serializers.Serializer
):
    role_id = serializers.UUIDField(required=False)
    location_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )
    all_locations = serializers.BooleanField(required=False)
    mode = serializers.ChoiceField(choices=AssignmentMode.choices, required=False)
    valid_from = serializers.DateTimeField(required=False, allow_null=True)
    valid_until = serializers.DateTimeField(required=False, allow_null=True)

    def validate_role_id(self, value):
        role = Role.objects.filter(id=value).first()
        if role is None:
            raise serializers.ValidationError("Role not found.")
        request = self.context.get("request")
        actor = getattr(request, "user", None) if request is not None else None
        if actor is not None:
            assert_role_assignable_by_actor(role=role, actor=actor)
        return value

    def validate(self, attrs):
        if not self.partial:
            required_fields = ("role_id", "location_ids", "all_locations", "mode")
            missing = [field for field in required_fields if field not in attrs]
            if missing:
                raise serializers.ValidationError(
                    {field: "This field is required for PUT." for field in missing}
                )

        if "all_locations" in attrs or "location_ids" in attrs:
            all_locations = attrs.get("all_locations")
            location_ids = attrs.get("location_ids")
            if all_locations is None or location_ids is None:
                assignment = self.context.get("assignment")
                if assignment is None:
                    raise serializers.ValidationError(
                        "assignment context is required for partial scope updates."
                    )
                if all_locations is None:
                    all_locations = assignment.all_locations
                if location_ids is None:
                    location_ids = list(
                        assignment.locations.values_list("branch_id", flat=True)
                    )
            self._validate_location_scope(
                all_locations=all_locations,
                location_ids=location_ids,
            )
        return attrs


class SwitchActiveTenantInputSerializer(serializers.Serializer):
    tenantId = serializers.UUIDField()


class SwitchActiveBranchInputSerializer(serializers.Serializer):
    branchId = serializers.UUIDField()


class PermissionOverrideCreateSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField()
    permission_id = serializers.UUIDField()
    effect = serializers.ChoiceField(choices=("allow", "deny"))


class MembershipPermissionOverrideCreateSerializer(serializers.Serializer):
    permission_id = serializers.UUIDField()
    effect = serializers.ChoiceField(choices=("allow", "deny"))


class PermissionOverrideUpdateSerializer(serializers.Serializer):
    effect = serializers.ChoiceField(choices=("allow", "deny"))


class RolePermissionReplaceSerializer(serializers.Serializer):
    permission_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
    )
