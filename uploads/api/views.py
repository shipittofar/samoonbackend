from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, inline_serializer

from uploads.api.serializers import (
    UploadAssetSerializer,
    UploadInitiateResponseSerializer,
    UploadInitiateSerializer,
)
from uploads.services.upload_bll import (
    cancel_upload,
    complete_upload,
    get_asset_for_actor,
    initiate_upload,
)


def _tenant_from_request(request, data_tenant_id=None):
    if data_tenant_id:
        return data_tenant_id
    header = request.headers.get("X-Tenant-Id") or request.META.get("HTTP_X_TENANT_ID")
    return header or None


class UploadInitiateAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["Uploads"],
        request=UploadInitiateSerializer,
        responses={201: UploadInitiateResponseSerializer},
        summary="Create an upload intent and presigned PUT URL",
        description=(
            "Creates a tenant-scoped UploadAsset and a short-lived S3-compatible PUT URL. "
            "Object keys are server-generated. The browser must PUT bytes to `upload.url` "
            "with the returned Content-Type header, then call complete. "
            "Purposes: user_avatar (self), tenant_* and website_media (settings.edit), "
            "menu_* (menu.manage + branch). Idempotency-Key header or body field is per user."
        ),
    )
    def post(self, request, *args, **kwargs):
        serializer = UploadInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        idempotency = data.get("idempotency_key") or request.headers.get("Idempotency-Key")
        asset, upload = initiate_upload(
            user=request.user,
            purpose=data["purpose"],
            filename=data["filename"],
            mime_type=data["mime_type"],
            byte_size=data["byte_size"],
            checksum=data.get("checksum") or "",
            tenant_id=_tenant_from_request(request, data.get("tenant_id")),
            entity_type=data.get("entity_type") or "",
            entity_id=data.get("entity_id") or "",
            branch_id=data.get("branch_id"),
            idempotency_key=idempotency or None,
        )
        payload = UploadAssetSerializer(asset).data
        payload["upload"] = upload
        return Response(payload, status=status.HTTP_201_CREATED)


class UploadCompleteAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["Uploads"],
        request=inline_serializer("UploadCompleteRequest", fields={}),
        responses={200: UploadAssetSerializer},
        summary="Verify stored object and enqueue processing",
        description=(
            "Ignores any client `uploaded` flag. The server HEADs the object at the "
            "asset storage key, checks size/MIME, decodes images, and optionally "
            "compares a SHA-256 checksum. Processing is asynchronous (Celery)."
        ),
    )
    def post(self, request, asset_id, *args, **kwargs):
        # Request body is intentionally unused. Client-supplied uploaded=true is untrusted.
        asset = complete_upload(asset_id=asset_id, user=request.user)
        return Response(UploadAssetSerializer(asset).data)


class UploadDetailAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["Uploads"],
        responses={200: UploadAssetSerializer},
        summary="Get upload asset status",
        description="Tenant-scoped. Cross-tenant reads are forbidden.",
    )
    def get(self, request, asset_id, *args, **kwargs):
        asset = get_asset_for_actor(asset_id, request.user)
        return Response(UploadAssetSerializer(asset).data)


class UploadCancelAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["Uploads"],
        responses={200: UploadAssetSerializer},
        summary="Cancel an unattached upload",
        description="Idempotent. Attached assets cannot be cancelled. Detached historical objects are not deleted.",
    )
    def post(self, request, asset_id, *args, **kwargs):
        asset = cancel_upload(asset_id=asset_id, user=request.user)
        return Response(UploadAssetSerializer(asset).data)
