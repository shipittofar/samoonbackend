from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.api.serializers.response.qr import (
    QrDestinationRequestSerializer,
    QrManagementResponseSerializer,
    serialize_qr_management,
)
from tenants.services.qr_bll import QrCodeBusinessLogicLayer


def _qr_response(qr, request) -> Response:
    return Response(
        QrManagementResponseSerializer(
            serialize_qr_management(qr, request)
        ).data
    )


@extend_schema(
    tags=["Tenant - QR"],
    summary="Retrieve tenant QR metadata",
    responses={200: QrManagementResponseSerializer},
)
class TenantQrRetrieveAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, tenant_id, *args, **kwargs):
        qr = QrCodeBusinessLogicLayer.get_tenant_qr(request.user, tenant_id)
        return _qr_response(qr, request)


@extend_schema(
    tags=["Tenant - QR"],
    summary="Enable tenant QR",
    request=None,
    responses={200: QrManagementResponseSerializer},
)
class TenantQrEnableAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, tenant_id, *args, **kwargs):
        qr = QrCodeBusinessLogicLayer.enable_tenant_qr(request.user, tenant_id)
        return _qr_response(qr, request)


@extend_schema(
    tags=["Tenant - QR"],
    summary="Disable tenant QR",
    request=None,
    responses={200: QrManagementResponseSerializer},
)
class TenantQrDisableAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, tenant_id, *args, **kwargs):
        qr = QrCodeBusinessLogicLayer.disable_tenant_qr(request.user, tenant_id)
        return _qr_response(qr, request)


@extend_schema(
    tags=["Tenant - QR"],
    summary="Regenerate tenant QR",
    description=(
        "Deactivates the current printed QR code and issues a new code. "
        "The old /qr/<code>/ URL returns 410. Destination type is preserved."
    ),
    request=None,
    responses={200: QrManagementResponseSerializer},
)
class TenantQrRegenerateAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, tenant_id, *args, **kwargs):
        qr = QrCodeBusinessLogicLayer.regenerate_tenant_qr(
            request.user, tenant_id
        )
        return _qr_response(qr, request)


@extend_schema(
    tags=["Tenant - QR"],
    summary="Change tenant QR destination",
    request=QrDestinationRequestSerializer,
    responses={200: QrManagementResponseSerializer},
)
class TenantQrDestinationAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, tenant_id, *args, **kwargs):
        serializer = QrDestinationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        qr = QrCodeBusinessLogicLayer.set_tenant_qr_destination(
            request.user,
            tenant_id,
            serializer.validated_data["destination_type"],
        )
        return _qr_response(qr, request)


@extend_schema(
    tags=["Tenant - QR"],
    summary="Retrieve branch QR metadata",
    responses={200: QrManagementResponseSerializer},
)
class BranchQrRetrieveAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, branch_id, *args, **kwargs):
        qr = QrCodeBusinessLogicLayer.get_branch_qr(request.user, branch_id)
        return _qr_response(qr, request)


@extend_schema(
    tags=["Tenant - QR"],
    summary="Enable branch QR",
    request=None,
    responses={200: QrManagementResponseSerializer},
)
class BranchQrEnableAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, branch_id, *args, **kwargs):
        qr = QrCodeBusinessLogicLayer.enable_branch_qr(request.user, branch_id)
        return _qr_response(qr, request)


@extend_schema(
    tags=["Tenant - QR"],
    summary="Disable branch QR",
    request=None,
    responses={200: QrManagementResponseSerializer},
)
class BranchQrDisableAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, branch_id, *args, **kwargs):
        qr = QrCodeBusinessLogicLayer.disable_branch_qr(request.user, branch_id)
        return _qr_response(qr, request)


@extend_schema(
    tags=["Tenant - QR"],
    summary="Regenerate branch QR",
    description=(
        "Deactivates the current printed QR code and issues a new code. "
        "The old /qr/<code>/ URL returns 410. Destination type is preserved."
    ),
    request=None,
    responses={200: QrManagementResponseSerializer},
)
class BranchQrRegenerateAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, branch_id, *args, **kwargs):
        qr = QrCodeBusinessLogicLayer.regenerate_branch_qr(
            request.user, branch_id
        )
        return _qr_response(qr, request)


@extend_schema(
    tags=["Tenant - QR"],
    summary="Change branch QR destination",
    request=QrDestinationRequestSerializer,
    responses={200: QrManagementResponseSerializer},
)
class BranchQrDestinationAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, branch_id, *args, **kwargs):
        serializer = QrDestinationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        qr = QrCodeBusinessLogicLayer.set_branch_qr_destination(
            request.user,
            branch_id,
            serializer.validated_data["destination_type"],
        )
        return _qr_response(qr, request)
