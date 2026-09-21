from rest_framework import serializers

from uploads.purposes import PURPOSE_REGISTRY


class UploadInitiateSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(
        choices=sorted(PURPOSE_REGISTRY.keys()),
        help_text="Upload purpose. Authorization is re-checked on attach, not only at initiate.",
    )
    filename = serializers.CharField(max_length=255)
    mime_type = serializers.CharField(max_length=128)
    byte_size = serializers.IntegerField(min_value=1)
    checksum = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional SHA-256 hex digest of the object bytes.",
    )
    tenant_id = serializers.UUIDField(required=False, allow_null=True)
    entity_type = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    entity_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    branch_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Required for menu_* purposes (do not send a menu row UUID as branch_id).",
    )
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


# Business APIs: omitted asset id = unchanged, null = detach, UUID = attach.
# Never send a file and an asset id in the same write.


class UploadInitiateResponseSerializer(UploadAssetSerializer):
    upload = serializers.DictField()
