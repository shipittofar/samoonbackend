# apps/menu/api/views/categories.py
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.generics import (
    CreateAPIView,
    UpdateAPIView,
    ListAPIView,
    RetrieveAPIView,
    DestroyAPIView
)
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema

from menu.api.serializers.request import (
    MenuCategoryInputSerializer,
    MenuCategoryUpdateSerializer,
    MenuCategoryBulkCreateInputSerializer
)
from menu.api.serializers.response import MenuCategoryOutputSerializer
from menu.authorization.branch_menu import RequireBranchMenuManagePermission
from menu.services import CategoryBusinessLogicLayer
from menu.models import MenuCategory
from tenants.models import Branch
from menu.api.views.tenant_summary import (
    MenuPublicTenantSummaryMixin,
    tenant_summary_for_branch,
)

category_bll = CategoryBusinessLogicLayer()


class CategoryPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


@extend_schema(tags=["Menu - Categories"], summary="create Menu Categories",
               request={
    "multipart/form-data": MenuCategoryInputSerializer,
},
)
class MenuCategoryCreateView(CreateAPIView):
    serializer_class = MenuCategoryInputSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def create(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        category = category_bll.create_menu_category(
            user=request.user,
            **input_serializer.validated_data
        )

        output_serializer = MenuCategoryOutputSerializer(category)
        return Response(
            output_serializer.data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Menu - Categories"], summary="Bulk create Menu Categories")
class MenuCategoryBulkCreateView(CreateAPIView):
    serializer_class = MenuCategoryBulkCreateInputSerializer
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def create(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        categories = category_bll.bulk_create_menu_categories(
            input_serializer.validated_data["categories"]
        )

        output_serializer = MenuCategoryOutputSerializer(categories, many=True)
        return Response(
            output_serializer.data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Menu - Categories"],
    summary="update partial Menu Categories",
    request={
        "multipart/form-data": MenuCategoryUpdateSerializer,
    },
)
class MenuCategoryUpdateView(UpdateAPIView):
    serializer_class = MenuCategoryUpdateSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]
    http_method_names = ["patch"]

    def patch(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        category = category_bll.update_menu_category(
            category_id=kwargs["pk"],
            branch_id=kwargs["branch_id"],
            **input_serializer.validated_data,
            image_provided="image" in request.data,
            image_asset_id_provided="image_asset_id" in request.data,
            user=request.user,
        )

        return Response(
            MenuCategoryOutputSerializer(category).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Menu - Categories"], summary="list Menu Categories")
class MenuCategoryListView(MenuPublicTenantSummaryMixin, ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MenuCategoryOutputSerializer
    pagination_class = CategoryPagination

    def get_queryset(self):
        return category_bll.get_category_list(
            branch_id=self.kwargs["branch_id"]
        )


@extend_schema(tags=["Menu - Categories"], summary="detail Menu Categories")
class MenuCategoryDetailView(RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = MenuCategoryOutputSerializer

    def retrieve(self, request, *args, **kwargs):
        branch_id = kwargs["branch_id"]
        category = category_bll.get_category_detail(
            category_id=kwargs["pk"],
            branch_id=branch_id,
        )
        payload = MenuCategoryOutputSerializer(category).data
        payload.update(tenant_summary_for_branch(branch_id))
        return Response(payload, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Menu - Categories"],
    summary="Delete empty category (refuses if items exist)",
)
class MenuCategoryDeleteView(DestroyAPIView):
    permission_classes = [IsAuthenticated, RequireBranchMenuManagePermission]

    def destroy(self, request, *args, **kwargs):
        CategoryBusinessLogicLayer.delete_menu_category(
            category_id=kwargs["pk"],
            branch_id=kwargs["branch_id"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Menu - Categories"], summary="list ALL Menu Categories (unfiltered, all tenants/branches)")
class MenuCategoryAllListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MenuCategoryOutputSerializer
    pagination_class = CategoryPagination

    def get_queryset(self):
        return category_bll.get_all_categories()


@extend_schema(tags=["Menu - Categories"], summary="list console Menu Categories (owned by current user)")
class ConsoleCategoryListView(ListAPIView):
    serializer_class = MenuCategoryOutputSerializer
    pagination_class = CategoryPagination
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return category_bll.get_console_categories(user=self.request.user)


@extend_schema(tags=["Menu - Categories"], summary="retrieve console Menu Category")
class ConsoleCategoryDetailView(RetrieveAPIView):
    serializer_class = MenuCategoryOutputSerializer
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        category = category_bll.get_console_category_detail(
            category_id=kwargs["pk"],
            user=request.user,
        )
        return Response(
            MenuCategoryOutputSerializer(category).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["Menu - Categories"], summary="retrieve console Menu Category")
class ConsoleCategoryDetailByBranchView(ListAPIView):
    serializer_class = MenuCategoryOutputSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch_id = self.kwargs["branch_id"]
        user = self.request.user

        print("=" * 50)
        print("Branch ID:", branch_id)
        print("User:", user)

        print(
            "Categories in branch:",
            MenuCategory.objects.filter(
                branch_id=branch_id
            ).count()
        )

        print(
            "Branch belongs to user:",
            Branch.objects.filter(
                id=branch_id,
                tenant__owner__user=user,
            ).exists()
        )

        queryset = category_bll.get_console_categoryies_detail_by_branch(
            branch_id=branch_id,
            user=user,
        )

        print("Final queryset count:", queryset.count())
        print("=" * 50)

        return queryset


@extend_schema(tags=["Menu - Categories"], summary="list console Menu Categories by tenant & branch")
class ConsoleCategoryByTenantBranchListView(ListAPIView):
    serializer_class = MenuCategoryOutputSerializer
    pagination_class = CategoryPagination
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return category_bll.get_console_categories_by_tenant_branch(
            user=self.request.user,
            tenant_id=self.kwargs["tenant_id"],
            branch_id=self.kwargs["branch_id"],
        )
