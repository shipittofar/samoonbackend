import logging

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.api.serializers.response.rbac import MePermissionsSerializer
from access.services.rbac_session_bll import rbac_session_bll

logger = logging.getLogger(__name__)


def _request_header_snapshot(request) -> dict:
    return {
        "authorization": bool(request.META.get("HTTP_AUTHORIZATION")),
        "x_tenant_slug": request.META.get("HTTP_X_TENANT_SLUG", "").strip() or None,
        "x_tenant_id": request.META.get("HTTP_X_TENANT_ID", "").strip() or None,
        "origin": request.META.get("HTTP_ORIGIN"),
    }


@extend_schema(
    tags=["Auth - authentication"],
    summary="Current user permissions",
    description="Returns effective permissions for the resolved tenant context.",
)
class MePermissionsView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        user_id = getattr(request.user, "id", None)
        headers = _request_header_snapshot(request)
        logger.info(
            "me_permissions_request user_id=%s path=%s headers=%s",
            user_id,
            request.path,
            headers,
        )
        try:
            payload = rbac_session_bll.build_permissions(user=request.user, request=request)
        except Exception:
            logger.exception(
                "me_permissions_failed user_id=%s path=%s headers=%s",
                user_id,
                request.path,
                headers,
            )
            raise

        logger.info(
            "me_permissions_success user_id=%s tenant_slug=%s permission_count=%s",
            user_id,
            headers["x_tenant_slug"],
            len(payload.get("permissions", [])),
        )
        serializer = MePermissionsSerializer(payload)
        return Response(serializer.data)
