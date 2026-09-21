from django.contrib import admin

from uploads.models import UploadAsset

# Django Admin ImageFields remain a documented legacy path. Application
# uploads must use /api/uploads/. Do not add a second Admin storage pipeline.


@admin.register(UploadAsset)
class UploadAssetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "purpose",
        "status",
        "tenant",
        "created_by",
        "byte_size",
        "created_at",
        "expires_at",
    )
    list_filter = ("purpose", "status")
    search_fields = ("id", "original_filename", "storage_key")
    readonly_fields = (
        "id",
        "tenant",
        "created_by",
        "purpose",
        "status",
        "storage_key",
        "variant_keys",
        "checksum",
        "mime_type",
        "byte_size",
        "idempotency_key",
        "created_at",
        "updated_at",
        "uploaded_at",
        "processed_at",
        "detached_at",
        "expires_at",
        "attached_to_type",
        "attached_to_id",
        "entity_type",
        "entity_id",
        "failure_code",
        "failure_message",
        "processing_attempts",
        "original_filename",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
