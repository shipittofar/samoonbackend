from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from superadmin.api.serializers import BusinessRequestSerializer
from tenants.models import BusinessRequest
from tenants.services import business_request_bll


@extend_schema(
    tags=["Tenant - Business requests"],
    summary="My business registration requests / file a new one",
    description=(
        "GET lists the signed-in user's requests (newest first). POST files a "
        "request; a platform superuser approves it, which creates the business "
        "and opens the console for the applicant."
    ),
)
class MyBusinessRequestsView(generics.ListCreateAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = BusinessRequestSerializer
    pagination_class = None

    def get_queryset(self):
        return BusinessRequest.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = business_request_bll.file_request(user=request.user, **serializer.validated_data)
        return Response(self.get_serializer(item).data, status=status.HTTP_201_CREATED)
