from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from menu.authorization.branch_menu import (
    RequireBranchMenuManagePermission,
    RequireBranchMenuViewPermission,
)
from menu.models import MenuTemplate
from menu.services.template_bll import apply_template, templates_for_tenant
from superadmin.api.serializers import MenuTemplateSerializer
from tenants.models import Branch


@extend_schema(tags=["Menu - Templates"], summary="Ready-made menus for this branch's business type")
class BranchMenuTemplateListView(APIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuViewPermission]

    def get(self, request, branch_id):
        branch = get_object_or_404(Branch.objects.select_related("tenant"), pk=branch_id)
        templates = templates_for_tenant(branch.tenant)
        return Response(MenuTemplateSerializer(templates, many=True).data)


@extend_schema(
    tags=["Menu - Templates"],
    summary="Copy a ready-made menu into this branch",
    description=(
        "Adds the template's categories and items to the branch. Categories with "
        "the same name are reused; items that already exist are skipped."
    ),
)
class BranchMenuTemplateApplyView(APIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def post(self, request, branch_id, template_id):
        template = get_object_or_404(MenuTemplate, pk=template_id)
        result = apply_template(template=template, branch_id=branch_id, user=request.user)
        return Response(result)
