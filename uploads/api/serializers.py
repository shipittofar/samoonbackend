from rest_framework import serializers

from uploads.purposes import PURPOSE_REGISTRY


class UploadInitiateSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=sorted(PURPOSE_REGISTRY.keys()))
    filename = serializers.CharField(max_length=255)
    mime_type = serializers.CharField(max_length=128)
    byte_size = serializers.IntegerField(min_value=1)
    checksum = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    tenant_id = serializers.UUIDField(required=False, allow_null=True)
    entity_type = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    entity_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    branch_id = serializers.UUIDField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=True)


class UploadAssetSerializer(serializers.Serializer):
    asset_id = serializers.UUIDField(source="id")
    purpose = serializers.CharField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField()
    failure_code = serializers.CharField()
    failure_message = serializers.CharField()
    variants = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    original_filename = serializers.CharField()
    mime_type = serializers.CharField()
    byte_size = serializers.IntegerField()

    def get_variants(self, obj):
        return obj.variant_keys or {}

    def get_url(self, obj):
        if obj.status in {"ready", "attached"}:
            return obj.public_url()
        return None


class UploadInitiateResponseSerializer(UploadAssetSerializer):
    upload = serializers.DictField()
