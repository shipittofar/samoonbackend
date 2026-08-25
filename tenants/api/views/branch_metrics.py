from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.api.serializers.response.branch_metrics import BranchMetricsResponseSerializer
from tenants.authorization import RequireBranchAnalyticsPermission
from tenants.services.branch_metrics_bll import BranchMetricsBusinessLogicLayer

branch_metrics_bll = BranchMetricsBusinessLogicLayer()


@extend_schema(
    tags=["Branches - Console"],
    summary="Branch metrics",
    description=(
        "Returns aggregate order, customer, and staff metrics for a branch. "
        "Console users only; requires analytics.view permission."
    ),
    parameters=[
        OpenApiParameter(
            name="period",
            type=str,
            enum=["day", "week", "month", "all"],
            description="Time window for order metrics (default: month).",
        ),
    ],
)
class BranchMetricsAPIView(APIView):
    permission_classes = (IsAuthenticated, RequireBranchAnalyticsPermission)

    def get(self, request, branch_id, *args, **kwargs):
        period = request.query_params.get("period", "month")
        try:
            metrics = branch_metrics_bll.get_branch_metrics(
                branch_id=branch_id,
                period=period,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(BranchMetricsResponseSerializer(metrics).data)
