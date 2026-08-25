from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from access.api.serializers.request import (
    PermissionOverrideCreateSerializer,
    PermissionOverrideUpdateSerializer,
    MembershipPermissionOverrideCreateSerializer,
)
from access.api.serializers.response.rbac import PermissionOverrideSerializer
from access.authorization import RequirePermission
from access.services.permission_override_bll import permission_override_bll
from core.exceptions import PermissionOverrideNotFoundException


@extend_schema(
    tags=["Access - Permission Override"],
    summary="List or create permission overrides",
)
class PermissionOverrideListCreateView(ListCreateAPIView):
    permission_classes = (IsAuthenticated, RequirePermission("staff.manage"))
    serializer_class = PermissionOverrideSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), RequirePermission("staff.view")()]
        return super().get_permissions()

    def get_queryset(self):
        return permission_override_bll.list_overrides(
            tenant_id=self.kwargs["tenant_id"],
            membership_id=self.request.query_params.get("membership_id"),
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return PermissionOverrideCreateSerializer
        return PermissionOverrideSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        override = permission_override_bll.create_override(
            tenant_id=kwargs["tenant_id"],
            membership_id=data["membership_id"],
            permission_id=data["permission_id"],
            effect=data["effect"],
            created_by_id=request.user.id,
        )
        return Response(
            PermissionOverrideSerializer(override).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Access - Permission Override"],
    summary="Update or delete a permission override",
)
class PermissionOverrideRetrieveUpdateDestroyView(RetrieveUpdateDestroyAPIView):
    permission_classes = (IsAuthenticated, RequirePermission("staff.manage"))
    serializer_class = PermissionOverrideSerializer
    lookup_url_kwarg = "override_id"

    def get_object(self):
        overrides = permission_override_bll.list_overrides(
            tenant_id=self.kwargs["tenant_id"],
        )
        override = overrides.filter(id=self.kwargs[self.lookup_url_kwarg]).first()
        if override is None:
            raise PermissionOverrideNotFoundException()
        return override

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return PermissionOverrideUpdateSerializer
        return PermissionOverrideSerializer

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        override = permission_override_bll.update_override(
            tenant_id=kwargs["tenant_id"],
            override_id=instance.id,
            effect=serializer.validated_data["effect"],
            actor_id=request.user.id,
        )
        return Response(PermissionOverrideSerializer(override).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        permission_override_bll.delete_override(
            tenant_id=kwargs["tenant_id"],
            override_id=instance.id,
            actor_id=request.user.id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Access - Permission Override"],
    summary="List or create permission overrides for a membership",
)
class MembershipPermissionOverrideListCreateView(ListCreateAPIView):
    permission_classes = (IsAuthenticated, RequirePermission("staff.manage"))
    serializer_class = PermissionOverrideSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), RequirePermission("staff.view")()]
        return super().get_permissions()

    def get_queryset(self):
        return permission_override_bll.list_overrides(
            tenant_id=self.kwargs["tenant_id"],
            membership_id=self.kwargs["membership_id"],
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return MembershipPermissionOverrideCreateSerializer
        return PermissionOverrideSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        override = permission_override_bll.create_override(
            tenant_id=kwargs["tenant_id"],
            membership_id=kwargs["membership_id"],
            permission_id=data["permission_id"],
            effect=data["effect"],
            created_by_id=request.user.id,
        )
        return Response(
            PermissionOverrideSerializer(override).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Access - Permission Override"],
    summary="Update or delete a membership permission override",
)
class MembershipPermissionOverrideRetrieveUpdateDestroyView(
    RetrieveUpdateDestroyAPIView
):
    permission_classes = (IsAuthenticated, RequirePermission("staff.manage"))
    serializer_class = PermissionOverrideSerializer
    lookup_url_kwarg = "override_id"

    def get_object(self):
        overrides = permission_override_bll.list_overrides(
            tenant_id=self.kwargs["tenant_id"],
            membership_id=self.kwargs["membership_id"],
        )
        override = overrides.filter(id=self.kwargs[self.lookup_url_kwarg]).first()
        if override is None:
            raise PermissionOverrideNotFoundException()
        return override

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return PermissionOverrideUpdateSerializer
        return PermissionOverrideSerializer

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        override = permission_override_bll.update_override(
            tenant_id=kwargs["tenant_id"],
            override_id=instance.id,
            effect=serializer.validated_data["effect"],
            actor_id=request.user.id,
        )
        return Response(PermissionOverrideSerializer(override).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        permission_override_bll.delete_override(
            tenant_id=kwargs["tenant_id"],
            override_id=instance.id,
            actor_id=request.user.id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
