from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    GenericAPIView,
    RetrieveAPIView,
    RetrieveDestroyAPIView,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from access.api.serializers.request import (
    RoleCreateSerializer,
    RolePermissionAddSerializer,
    RolePermissionReplaceSerializer,
)
from access.api.serializers.response import PermissionSerializer, RoleSerializer
from access.authorization import CanManageRoleDefinitions, user_can_manage_role_definitions
from core.exceptions import (
    PermissionNotFoundException,
    RoleNotFoundException
)
from access.selectors import role_selector
from access.services.role_bll import role_service


@extend_schema(
    tags=["Access - Role"],
    summary="List or create roles",
    description="Returns all system roles or creates a new role."
)
class RoleListCreateView(ListCreateAPIView):
    permission_classes = (IsAuthenticated, CanManageRoleDefinitions)

    def get_queryset(self):
        return role_selector.get_role_queryset(viewer=self.request.user)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return RoleCreateSerializer
        return RoleSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        role = role_service.create_role(
            actor_id=request.user.id,
            actor=request.user,
            can_manage_roles=user_can_manage_role_definitions(request.user),
            **serializer.validated_data,
        )

        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Access - Role"],
    summary="Retrieve or delete role",
    description="Returns details of a specific role or permanently deletes it."
)
class RoleRetrieveDestroyView(RetrieveDestroyAPIView):
    permission_classes = (IsAuthenticated, CanManageRoleDefinitions)
    serializer_class = RoleSerializer
    lookup_url_kwarg = "role_id"

    def get_object(self):
        role = role_selector.get_role_by_id(
            role_id=self.kwargs[self.lookup_url_kwarg],
            viewer=self.request.user,
        )
        if role is None:
            raise RoleNotFoundException()
        return role

    def destroy(self, request, *args, **kwargs):
        role_service.delete_role(
            role_id=kwargs[self.lookup_url_kwarg],
            actor_id=request.user.id,
            can_manage_roles=user_can_manage_role_definitions(request.user),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Access - Role"],
    summary="List, replace, or add role permissions",
    description=(
        "GET returns the role's permissions. PUT replaces all permissions atomically. "
        "POST adds permissions without removing existing ones."
    ),
)
class RolePermissionManageView(GenericAPIView):
    permission_classes = (IsAuthenticated, CanManageRoleDefinitions)

    def get(self, request, *args, **kwargs):
        role = role_selector.get_role_by_id(
            role_id=kwargs["role_id"], viewer=request.user
        )
        if role is None:
            raise RoleNotFoundException()
        permissions = role_service.get_role_permissions(role_id=kwargs["role_id"])
        return Response(PermissionSerializer(permissions, many=True).data)

    def put(self, request, *args, **kwargs):
        role = role_selector.get_role_by_id(
            role_id=kwargs["role_id"], viewer=request.user
        )
        if role is None:
            raise RoleNotFoundException()
        serializer = RolePermissionReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        role_service.replace_role_permissions(
            role_id=kwargs["role_id"],
            permission_ids=serializer.validated_data["permission_ids"],
            actor_id=request.user.id,
            can_manage_roles=user_can_manage_role_definitions(request.user),
        )
        permissions = role_service.get_role_permissions(role_id=kwargs["role_id"])
        return Response(PermissionSerializer(permissions, many=True).data)

    def post(self, request, *args, **kwargs):
        role = role_selector.get_role_by_id(
            role_id=kwargs["role_id"], viewer=request.user
        )
        if role is None:
            raise RoleNotFoundException()
        serializer = RolePermissionAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        role = role_service.add_permissions(
            role_id=kwargs["role_id"],
            permission_slugs=serializer.validated_data["permission_slugs"],
            actor_id=request.user.id,
            can_manage_roles=user_can_manage_role_definitions(request.user),
        )

        return Response(RoleSerializer(role).data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Access - Role"],
    summary="Add permissions to role",
    description="Assigns one or more permissions to an existing role.",
    deprecated=True,
)
class RolePermissionAddView(RolePermissionManageView):
    """Backward-compatible alias — POST-only callers may use this name."""


@extend_schema(
    tags=["Access - Permission"],
    summary="List permissions",
    description="Returns all available system permissions."
)
class PermissionListView(ListAPIView):
    permission_classes = (IsAuthenticated, CanManageRoleDefinitions)
    serializer_class = PermissionSerializer

    def get_queryset(self):
        return role_selector.get_permission_queryset()


@extend_schema(
    tags=["Access - Permission"],
    summary="Retrieve permission",
    description="Returns details of a specific system permission."
)
class PermissionRetrieveView(RetrieveAPIView):
    permission_classes = (IsAuthenticated, CanManageRoleDefinitions)
    serializer_class = PermissionSerializer
    lookup_url_kwarg = "permission_id"

    def get_object(self):
        permission = role_selector.get_permission_by_id(
            permission_id=self.kwargs[self.lookup_url_kwarg]
        )
        if permission is None:
            raise PermissionNotFoundException()
        return permission