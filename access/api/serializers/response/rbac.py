from rest_framework import serializers


class TenantRoleSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField()
    tenant_slug = serializers.CharField()
    is_active = serializers.BooleanField()
    status = serializers.CharField()
    role = serializers.CharField()
    permissions = serializers.ListField(child=serializers.CharField())


class BillingRefSerializer(serializers.Serializer):
    customerId = serializers.CharField(allow_null=True)
    billingEmail = serializers.EmailField(allow_null=True)


class OwnershipSerializer(serializers.Serializer):
    ownerId = serializers.UUIDField()
    userId = serializers.UUIDField()
    status = serializers.CharField(allow_null=True)
    plan = serializers.CharField(allow_null=True)
    maxTenants = serializers.IntegerField(allow_null=True)
    billing = BillingRefSerializer()
    createdAt = serializers.DateTimeField()
    verifiedAt = serializers.DateTimeField(allow_null=True, required=False)


class StaffAssignmentSerializer(serializers.Serializer):
    assignmentId = serializers.UUIDField()
    staffId = serializers.UUIDField()
    tenantId = serializers.UUIDField()
    tenantIsActive = serializers.BooleanField()
    tenantStatus = serializers.CharField()
    branchIds = serializers.JSONField()
    role = serializers.CharField()
    mode = serializers.CharField(allow_null=True)
    status = serializers.CharField(allow_null=True)
    validFrom = serializers.DateTimeField(allow_null=True)
    validUntil = serializers.DateTimeField(allow_null=True)
    grantedBy = serializers.UUIDField(allow_null=True)
    grantedAt = serializers.DateTimeField()


class PermissionCatalogSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    key = serializers.CharField()
    resource = serializers.CharField()
    action = serializers.CharField()
    description = serializers.CharField()


class TenantRoleListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    is_system_role = serializers.BooleanField()
    editable = serializers.BooleanField()
    permissions = serializers.ListField(child=serializers.CharField())


class MePermissionsSerializer(serializers.Serializer):
    permissions = serializers.ListField(child=serializers.CharField())


class EffectivePermissionsSerializer(serializers.Serializer):
    permissions = serializers.ListField(child=serializers.CharField())
    inherited_permissions = serializers.ListField(child=serializers.CharField())
    overrides = serializers.ListField(child=serializers.DictField())


class PermissionOverridePermissionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    slug = serializers.CharField()
    resource = serializers.CharField()
    action = serializers.CharField()
    description = serializers.CharField()


class PermissionOverrideSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    membership = serializers.UUIDField(source="membership.id")
    permission = PermissionOverridePermissionSerializer()
    effect = serializers.CharField()
    created_by = serializers.UUIDField(source="created_by_id")
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class PermissionAuditSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    action = serializers.CharField()
    actor = serializers.UUIDField(source="actor_id", allow_null=True)
    tenant = serializers.UUIDField(source="tenant_id", allow_null=True)
    tenant_is_active = serializers.BooleanField(source="tenant.is_active", allow_null=True)
    tenant_status = serializers.CharField(source="tenant.status", allow_null=True)
    membership = serializers.UUIDField(source="membership_id", allow_null=True)
    assignment = serializers.UUIDField(source="assignment_id", allow_null=True)
    permission = serializers.UUIDField(source="permission_id", allow_null=True)
    metadata = serializers.JSONField()
    created_at = serializers.DateTimeField()
