from rest_framework import serializers

from access.api.serializers.response.rbac import (
    OwnershipSerializer,
    StaffAssignmentSerializer,
    TenantRoleSerializer,
)
from access.services.assignment_scope import (
    collect_accessible_branch_ids,
    membership_has_tenant_wide_scope,
)
from access.authorization.admin_role_protection import filter_role_slugs
from accounts.models import User
from tenants.api.serializers.response.tenant_summary import TenantSummarySerializer


class TokenOutputSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class UserOutputSerializer(serializers.ModelSerializer):
    phone_number = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "phone_number", "first_name", "last_name",
            "avatar", "role", "is_verified", "is_superuser", "created_at",
        ]

    def get_phone_number(self, obj):
        return obj.phone_number or None

    def get_avatar(self, obj):
        if not obj.avatar:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.avatar.url) if request else obj.avatar.url


class VerifyOTPOutputSerializer(serializers.Serializer):
    user = UserOutputSerializer()
    is_new_user = serializers.BooleanField()
    tokens = TokenOutputSerializer()


class AccountVerifyOutputSerializer(serializers.Serializer):
    is_verified = serializers.BooleanField()
    missing_fields = serializers.ListField(child=serializers.CharField(), required=False)


class BranchOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    status = serializers.CharField()
    isDefault = serializers.BooleanField(source="is_default")


class MembershipOutputSerializer(serializers.Serializer):
    tenantId = serializers.UUIDField(source="tenant.id")
    tenantName = serializers.CharField(source="tenant.name")
    tenantSlug = serializers.CharField(source="tenant.slug")
    tenantIsActive = serializers.BooleanField(source="tenant.is_active")
    tenantStatus = serializers.CharField(source="tenant.status")
    tenant = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()
    branchAccess = serializers.SerializerMethodField()
    branches = serializers.SerializerMethodField()

    def get_tenant(self, membership):
        tenant = membership["tenant"]
        return TenantSummarySerializer(
            {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "is_active": tenant.is_active,
                "status": tenant.status,
            }
        ).data

    def get_roles(self, membership):
        if membership.get("is_owner"):
            return ["owner"]
        request = self.context.get("request")
        viewer = getattr(request, "user", None) if request else None
        roles = list(
            membership["assignments"].values_list("role__slug", flat=True).distinct()
        )
        return filter_role_slugs(roles, viewer)

    def get_branchAccess(self, membership):
        if membership.get("is_owner"):
            return {"scope": "all"}
        assignments = membership["assignments"]
        if membership_has_tenant_wide_scope(assignments):
            return {"scope": "all"}
        return {"scope": "selected"}

    def get_branches(self, membership):
        tenant = membership["tenant"]
        if membership.get("is_owner"):
            branches = tenant.branches.all()
        else:
            branch_ids = collect_accessible_branch_ids(membership["assignments"])
            if branch_ids is None:
                branches = tenant.branches.all()
            else:
                branches = tenant.branches.filter(id__in=branch_ids)
        return BranchOutputSerializer(branches, many=True).data


class ActiveMembershipOutputSerializer(serializers.Serializer):
    tenantId = serializers.UUIDField(allow_null=True)
    branchId = serializers.UUIDField(allow_null=True)
    tenantIsActive = serializers.BooleanField(required=False, allow_null=True)
    tenantStatus = serializers.CharField(required=False, allow_null=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if isinstance(instance, dict):
            for field in ("tenantIsActive", "tenantStatus"):
                if field not in instance:
                    data.pop(field, None)
        return data


class UserMeOutputSerializer(serializers.Serializer):
    user = serializers.DictField()
    memberships = MembershipOutputSerializer(many=True)
    activeMembership = ActiveMembershipOutputSerializer(allow_null=True)
    tenantRoles = TenantRoleSerializer(many=True)
    ownership = OwnershipSerializer(many=True)
    staffAssignments = StaffAssignmentSerializer(many=True)