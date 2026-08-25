from rest_framework import serializers

from access.models import Permission, Role, StaffMembership
from tenants.api.serializers.response.tenant_summary import TenantSummarySerializer


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ("id", "slug", "name", "description", "system_role", "created_at", "updated_at")


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ("id", "resource", "action", "slug", "description")


class StaffMembershipUserDataSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField(allow_null=True)
    first_name = serializers.CharField(allow_null=True)
    last_name = serializers.CharField(allow_null=True)
    phone_number = serializers.CharField(allow_null=True)


class StaffMembershipSerializer(serializers.ModelSerializer):
    """Roster-friendly membership payload; keeps legacy `user`/`tenant` PK fields."""

    user_id = serializers.UUIDField(read_only=True)
    email = serializers.SerializerMethodField()
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    user_data = serializers.SerializerMethodField()
    tenant_is_active = serializers.BooleanField(source="tenant.is_active", read_only=True)
    tenant_status = serializers.CharField(source="tenant.status", read_only=True)
    tenant_summary = serializers.SerializerMethodField()

    class Meta:
        model = StaffMembership
        fields = (
            "id",
            "tenant",
            "tenant_is_active",
            "tenant_status",
            "tenant_summary",
            "user",
            "user_id",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "user_data",
            "status",
            "invited_by",
            "joined_at",
            "created_at",
            "updated_at",
        )

    def get_email(self, obj):
        return obj.user.email if obj.user_id else None

    def get_first_name(self, obj):
        return obj.user.first_name if obj.user_id else None

    def get_last_name(self, obj):
        return obj.user.last_name if obj.user_id else None

    def get_phone_number(self, obj):
        return obj.user.phone_number if obj.user_id else None

    def get_user_data(self, obj):
        if not obj.user_id:
            return None
        user = obj.user
        return {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number,
        }

    def get_tenant_summary(self, obj):
        tenant = obj.tenant
        return TenantSummarySerializer(
            {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "is_active": tenant.is_active,
                "status": tenant.status,
            }
        ).data


class StaffAssignmentRoleOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    slug = serializers.CharField()
    name = serializers.CharField()


class StaffAssignmentLocationOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class StaffAssignmentSerializer(serializers.Serializer):
    assignment_id = serializers.UUIDField(source="id")
    membership_id = serializers.UUIDField()
    user_id = serializers.UUIDField(source="membership.user_id")
    tenant_is_active = serializers.BooleanField(
        source="membership.tenant.is_active", read_only=True
    )
    tenant_status = serializers.CharField(
        source="membership.tenant.status", read_only=True
    )
    tenant = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    locations = serializers.SerializerMethodField()
    all_locations = serializers.BooleanField()
    mode = serializers.CharField()
    status = serializers.CharField()
    valid_from = serializers.DateTimeField(allow_null=True)
    valid_until = serializers.DateTimeField(allow_null=True)
    granted_by = serializers.UUIDField(source="granted_by_id", allow_null=True)
    granted_at = serializers.DateTimeField(allow_null=True)
    revoked_by = serializers.UUIDField(source="revoked_by_id", allow_null=True)
    revoked_at = serializers.DateTimeField(allow_null=True)

    def get_tenant(self, obj):
        tenant = obj.membership.tenant
        return TenantSummarySerializer(
            {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "is_active": tenant.is_active,
                "status": tenant.status,
            }
        ).data

    def get_role(self, obj):
        return {
            "id": str(obj.role_id),
            "slug": obj.role.slug,
            "name": obj.role.name,
        }

    def get_locations(self, obj):
        if obj.all_locations:
            return []

        locations = []
        seen: set = set()
        for location in obj.locations.all():
            branch = location.branch
            if branch.id in seen:
                continue
            seen.add(branch.id)
            locations.append({"id": str(branch.id), "name": branch.name})

        return locations
