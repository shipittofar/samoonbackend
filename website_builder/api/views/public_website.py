from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from website_builder.api.serializers.public_website import PublicWebsiteResponseSerializer
from website_builder.services import WebsiteBuilderBusinessLogicLayer

website_bll = WebsiteBuilderBusinessLogicLayer()


@extend_schema(
    tags=["Public - Website"],
    summary="Get published public website content",
    responses={200: PublicWebsiteResponseSerializer},
)
class PublicWebsiteAPIView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request, tenant_id, *args, **kwargs):
        payload = website_bll.get_public_website(tenant_id=tenant_id)
        return Response(PublicWebsiteResponseSerializer(payload).data)
