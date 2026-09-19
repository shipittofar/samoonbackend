from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from django.http import HttpResponseRedirect

from tenants.services.qr_bll import QrCodeBusinessLogicLayer


@extend_schema(
    tags=["Public - QR"],
    summary="Resolve a printed QR code",
    description=(
        "Looks up the stable QR identifier and issues a temporary redirect "
        "to the current public destination (tenant or branch storefront). "
        "Printed QR images should encode this URL, not the destination path."
    ),
    parameters=[
        OpenApiParameter(
            name="code",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="Opaque public QR identifier.",
        ),
    ],
    responses={
        302: OpenApiResponse(description="Redirect to the current destination URL."),
        404: OpenApiResponse(description="QR code or target entity not found."),
        410: OpenApiResponse(description="QR code has been disabled."),
    },
)
class QrResolveAPIView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request, code: str, *args, **kwargs):
        url = QrCodeBusinessLogicLayer.resolve_redirect_url(code)
        return HttpResponseRedirect(url)
