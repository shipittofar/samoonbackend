from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.api.serializers.request.favorite import FavoriteCreateRequestSerializer
from accounts.api.serializers.response.favorite import (
    FavoriteListResponseSerializer,
    FavoriteMutationResponseSerializer,
    FavoriteResponseSerializer,
    FavoriteSyncResponseSerializer,
)
from accounts.services.favorite_bll import FavoriteBusinessLogicLayer
from accounts.utils.favorite_sync import compute_favorites_sync_state

favorite_bll = FavoriteBusinessLogicLayer()


class FavoritePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


def _parse_branch_id(request) -> UUID | None:
    raw = request.query_params.get("branch_id")
    if not raw:
        return None
    return UUID(raw)


@extend_schema(
    tags=["Users - Favorites"],
    summary="List favorites with menu item metadata",
    description=(
        "Return the authenticated user's favorites as paginated objects. "
        "Includes sync metadata so clients can detect stale local state."
    ),
    parameters=[
        OpenApiParameter(name="branch_id", type=str,
                         location=OpenApiParameter.QUERY, required=False),
        OpenApiParameter(name="page", type=int,
                         location=OpenApiParameter.QUERY, required=False),
        OpenApiParameter(name="page_size", type=int,
                         location=OpenApiParameter.QUERY, required=False),
    ],
    responses={200: FavoriteListResponseSerializer},
)
class FavoriteListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = FavoritePagination

    def get(self, request):
        branch_id = _parse_branch_id(request)
        queryset = favorite_bll.list_favorites(
            request.user, branch_id=branch_id)
        sync = compute_favorites_sync_state(
            user_id=request.user.id, branch_id=branch_id)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = FavoriteResponseSerializer(page, many=True)
        payload = {
            "sync": sync,
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return Response(payload)

    @extend_schema(
        summary="Add a favorite",
        request=FavoriteCreateRequestSerializer,
        responses={201: FavoriteMutationResponseSerializer,
                   200: FavoriteMutationResponseSerializer},
    )
    def post(self, request):
        serializer = FavoriteCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = favorite_bll.add_favorite(
            request.user,
            serializer.validated_data["menu_item_id"],
        )
        response_serializer = FavoriteMutationResponseSerializer(
            {
                "favorite": result["favorite"],
                "sync": result["sync"],
                "created": result["created"],
            }
        )
        status_code = status.HTTP_201_CREATED if result["created"] else status.HTTP_200_OK
        return Response(response_serializer.data, status=status_code)


@extend_schema(
    tags=["Users - Favorites"],
    summary="Get favorites sync snapshot",
    description=(
        "Lightweight endpoint for bootstrap, reconnect, and multi-tab synchronization. "
        "Returns the current sync version and the full set of favorite menu item IDs."
    ),
    parameters=[
        OpenApiParameter(name="branch_id", type=str,
                         location=OpenApiParameter.QUERY, required=False),
    ],
    responses={200: FavoriteSyncResponseSerializer},
)
class FavoriteSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        branch_id = _parse_branch_id(request)
        payload = favorite_bll.get_sync_state(
            request.user, branch_id=branch_id)
        serializer = FavoriteSyncResponseSerializer(payload)
        return Response(serializer.data)


@extend_schema(
    tags=["Users - Favorites"],
    summary="Remove a favorite",
    description="Idempotently remove a menu item from the authenticated user's favorites.",
    responses={200: FavoriteMutationResponseSerializer},
)
class FavoriteDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, menu_item_id):
        result = favorite_bll.remove_favorite(request.user, menu_item_id)
        response_serializer = FavoriteMutationResponseSerializer(
            {
                "favorite": None,
                "removed": result["removed"],
                "menu_item_id": result["menu_item_id"],
                "sync": result["sync"],
            }
        )
        return Response(response_serializer.data)

    @extend_schema(
        summary="[Deprecated] Toggle favorite menu item",
        description="Deprecated. Use POST /users/favorites/ to add and DELETE /users/favorites/{menu_item_id}/ to remove.",
        deprecated=True,
        responses={200: FavoriteMutationResponseSerializer},
    )
    def post(self, request, menu_item_id):
        existing = (
            favorite_bll.list_favorites(request.user)
            .filter(menu_item_id=menu_item_id)
            .first()
        )
        if existing is not None:
            result = favorite_bll.remove_favorite(request.user, menu_item_id)
            response_serializer = FavoriteMutationResponseSerializer(
                {
                    "favorite": None,
                    "removed": result["removed"],
                    "menu_item_id": result["menu_item_id"],
                    "sync": result["sync"],
                }
            )
            return Response(
                response_serializer.data,
                headers={"Deprecation": "true", "Sunset": "2026-12-01"},
            )

        result = favorite_bll.add_favorite(request.user, menu_item_id)
        response_serializer = FavoriteMutationResponseSerializer(
            {
                "favorite": result["favorite"],
                "sync": result["sync"],
                "created": result["created"],
            }
        )
        return Response(
            response_serializer.data,
            headers={"Deprecation": "true", "Sunset": "2026-12-01"},
        )
