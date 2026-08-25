from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.api.serializers.response.rbac import EffectivePermissionsSerializer
from access.services.rbac_bll import rbac_bll
from access.services.rbac_session_bll import rbac_session_bll


@extend_schema(
    tags=["Auth - authentication"],
    summary="Effective permissions breakdown",
    description=(
        "Returns effective permissions with inherited role permissions and "
        "per-membership override effects for the resolved tenant context. "
        "Without subject query params, returns the authenticated user's permissions. "
        "With membership_id and/or user_id, returns that staff member's permissions "
        "(requires Owner, staff.view, or staff.manage when inspecting another user)."
    ),
    parameters=[
        OpenApiParameter(
            name="membership_id",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Staff membership UUID in the resolved tenant.",
        ),
        OpenApiParameter(
            name="user_id",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Staff user UUID with an active membership in the resolved tenant.",
        ),
    ],
)
class MeEffectivePermissionsView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        tenant = rbac_bll.resolve_tenant_context(user=request.user, request=request)
        subject = rbac_session_bll.resolve_effective_permissions_subject(
            actor=request.user,
            tenant=tenant,
            membership_id=request.query_params.get("membership_id"),
            user_id=request.query_params.get("user_id"),
        )
        payload = rbac_bll.get_effective_permissions_breakdown(
            user=subject,
            tenant=tenant,
            use_cache=True,
        )
        serializer = EffectivePermissionsSerializer(payload)
        return Response(serializer.data)
