from rest_framework.pagination import PageNumberPagination
from rest_framework.generics import (
    CreateAPIView,
    UpdateAPIView,
    ListAPIView,
    RetrieveAPIView,
    DestroyAPIView,
)
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated

from menu.api.serializers.request import (
    ExtraGroupInputSerializer,
    ExtraGroupUpdateSerializer,
    ExtraGroupReorderSerializer,
)
from menu.api.serializers.response import ExtraGroupOutputSerializer
from menu.services.extra_group_bll import ExtraGroupBusinessLogicLayer


extra_group_bll = ExtraGroupBusinessLogicLayer()


class ExtraGroupPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _resolve_branch_id(request, kwargs):
    """Support path-based branch_id and query-param alias routes."""
    return kwargs.get("branch_id") or request.query_params.get("branch_id")


@extend_schema(
    tags=["Menu - Extra Groups"],
    summary="create Extra Group",
    description="Create a new extra group for the specified branch.",
)
class ExtraGroupCreateView(CreateAPIView):
    serializer_class = ExtraGroupInputSerializer

    def create(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        group = extra_group_bll.create_extra_group(
            **input_serializer.validated_data
        )

        return Response(
            ExtraGroupOutputSerializer(group).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Menu - Extra Groups"],
    summary="list Extra Groups",
    description="Retrieve a paginated list of extra groups for the specified branch.",
)
class ExtraGroupListView(ListAPIView):
    serializer_class = ExtraGroupOutputSerializer
    pagination_class = ExtraGroupPagination

    def get_queryset(self):
        branch_id = _resolve_branch_id(self.request, self.kwargs)
        return extra_group_bll.get_extra_group_list(branch_id=branch_id)


@extend_schema(
    tags=["Console - Menu - Extra Groups"],
    summary="Console list Extra Groups",
    description="Retrieve a paginated list of extra groups for the specified branch from console menu.",
)
class ConsoleExtraGroupListView(ListAPIView):
    serializer_class = ExtraGroupOutputSerializer
    pagination_class = ExtraGroupPagination
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        branch_id = _resolve_branch_id(self.request, self.kwargs)
        return extra_group_bll.get_extra_group_list_for_console(branch_id=branch_id)


@extend_schema(
    tags=["Menu - Extra Groups"],
    summary="detail Extra Group",
    description="Retrieve the details of a specific extra group.",
)
class ExtraGroupDetailView(RetrieveAPIView):
    serializer_class = ExtraGroupOutputSerializer

    def retrieve(self, request, *args, **kwargs):
        group = extra_group_bll.get_extra_group_detail(
            group_id=kwargs["pk"],
            branch_id=_resolve_branch_id(request, kwargs),
        )
        return Response(
            ExtraGroupOutputSerializer(group).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Extra Groups"],
    summary="update partial Extra Group",
    description="Partially update an existing extra group.",
)
class ExtraGroupUpdateView(UpdateAPIView):
    serializer_class = ExtraGroupUpdateSerializer
    http_method_names = ["patch"]

    def partial_update(self, request, *args, **kwargs):
        input_serializer = self.get_serializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        group = extra_group_bll.update_extra_group(
            group_id=kwargs["pk"],
            branch_id=_resolve_branch_id(request, kwargs),
            **input_serializer.validated_data,
        )

        return Response(
            ExtraGroupOutputSerializer(group).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Extra Groups"],
    summary="delete Extra Group",
    description="Delete an existing extra group.",
)
class ExtraGroupDeleteView(DestroyAPIView):

    def destroy(self, request, *args, **kwargs):
        extra_group_bll.delete_extra_group(
            group_id=kwargs["pk"],
            branch_id=_resolve_branch_id(request, kwargs),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Menu - Extra Groups"],
    summary="reorder Extra Groups",
    description="Persist a new display order for all extra groups in a branch.",
)
class ExtraGroupReorderView(APIView):

    def patch(self, request, *args, **kwargs):
        input_serializer = ExtraGroupReorderSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        branch_id = _resolve_branch_id(request, kwargs)
        groups = extra_group_bll.reorder_extra_groups(
            branch_id=branch_id,
            ordered_ids=input_serializer.validated_data["order"],
        )

        return Response(
            ExtraGroupOutputSerializer(groups, many=True).data,
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Menu - Extra Groups"],
    summary="Extra Group collection (frontend alias)",
    description="GET list, POST create, or PATCH reorder via /extra-groups/.",
)
class ExtraGroupCollectionAliasView(APIView):

    def get(self, request, *args, **kwargs):
        branch_id = _resolve_branch_id(request, kwargs)
        groups = extra_group_bll.get_extra_group_list(branch_id=branch_id)
        serializer = ExtraGroupOutputSerializer(groups, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        input_serializer = ExtraGroupInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        group = extra_group_bll.create_extra_group(
            **input_serializer.validated_data
        )
        return Response(
            ExtraGroupOutputSerializer(group).data,
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request, *args, **kwargs):
        return ExtraGroupReorderView().patch(request, *args, **kwargs)


@extend_schema(
    tags=["Menu - Extra Groups"],
    summary="Extra Group detail (frontend alias)",
    description="GET, PATCH, or DELETE via /extra-groups/{id}/.",
)
class ExtraGroupDetailAliasView(APIView):

    def get(self, request, *args, **kwargs):
        group = extra_group_bll.get_extra_group_detail(
            group_id=kwargs["pk"],
            branch_id=_resolve_branch_id(request, kwargs),
        )
        return Response(
            ExtraGroupOutputSerializer(group).data,
            status=status.HTTP_200_OK,
        )

    def patch(self, request, *args, **kwargs):
        input_serializer = ExtraGroupUpdateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        group = extra_group_bll.update_extra_group(
            group_id=kwargs["pk"],
            branch_id=_resolve_branch_id(request, kwargs),
            **input_serializer.validated_data,
        )
        return Response(
            ExtraGroupOutputSerializer(group).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request, *args, **kwargs):
        extra_group_bll.delete_extra_group(
            group_id=kwargs["pk"],
            branch_id=_resolve_branch_id(request, kwargs),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
