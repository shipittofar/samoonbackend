from drf_spectacular.utils import extend_schema
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.authorization import RequirePermission
from superadmin.api.permissions import IsPlatformSuperuser
from tenants.models import Tenant
from platform_settings.services import homepage_hero, platform_config


@extend_schema(tags=["Platform - Homepage"])
class HomepageHeroView(APIView):
    """GET: public (the marketplace home page reads it; 404 until a superuser
    saves one, and the site then shows its built-in default).
    PUT: platform superusers only; replaces the whole hero."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsPlatformSuperuser()]

    def perform_authentication(self, request):
        # The public read never looks at the user, so an expired token sent by
        # a visitor's browser must not turn the home page hero into a 401.
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        super().perform_authentication(request)

    def get(self, request):
        hero = homepage_hero.get_hero()
        if hero is None:
            return Response({"detail": "The homepage hero has not been configured."}, status=404)
        return Response(hero)

    def put(self, request):
        return Response(homepage_hero.save_hero(user=request.user, data=request.data))


class _PublicReadMixin:
    """GET is public and never authenticates (a stale token must not break
    the site); writes are platform-superuser only."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsPlatformSuperuser()]

    def perform_authentication(self, request):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        super().perform_authentication(request)


@extend_schema(tags=["Platform - Configuration"])
class PlatformConfigView(_PublicReadMixin, APIView):
    """Platform-level overrides of Platform Configuration fields.

    GET (public): ``{"overrides": {fieldId: value}}``.
    PUT (superusers): ``{"changes": [{"fieldId", "value"} | {"fieldId", "reset": true}], "reason"}``
    applies all changes or none, logs each, and returns the new overrides.
    """

    def get(self, request):
        response = Response({"overrides": platform_config.get_overrides()})
        response["Cache-Control"] = "no-store"
        return response

    def put(self, request):
        return Response({"overrides": platform_config.save_overrides(user=request.user, data=request.data)})


@extend_schema(tags=["Platform - Configuration"])
class PlatformConfigHistoryView(APIView):
    """Change log (superusers only). ``?field=<fieldId>&limit=100``."""

    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit", 100))
        except ValueError:
            limit = 100
        field_id = request.query_params.get("field") or None
        return Response({"results": platform_config.history(field_id=field_id, limit=limit)})


@extend_schema(tags=["Tenant - Configuration"])
class TenantConfigView(APIView):
    """A business's values for tenant-level Platform Configuration fields.

    GET (public, like the storefront settings it feeds): ``{"overrides": {fieldId: value}}``.
    PUT (settings.manage on the business — owners, settings managers,
    platform superusers): same body as /api/platform/config/.
    """

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsAuthenticated(), RequirePermission("settings.manage")()]

    def perform_authentication(self, request):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        super().perform_authentication(request)

    def get(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, id=tenant_id)
        response = Response({"overrides": platform_config.get_tenant_overrides(tenant.id)})
        response["Cache-Control"] = "no-store"
        return response

    def put(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, id=tenant_id)
        return Response({"overrides": platform_config.save_tenant_overrides(user=request.user, tenant=tenant, data=request.data)})


@extend_schema(tags=["Tenant - Configuration"])
class TenantConfigHistoryView(APIView):
    """A business's configuration change log (settings.view). ``?field=&limit=``."""

    permission_classes = [IsAuthenticated, RequirePermission("settings.view")]

    def get(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, id=tenant_id)
        try:
            limit = int(request.query_params.get("limit", 100))
        except ValueError:
            limit = 100
        field_id = request.query_params.get("field") or None
        return Response({"results": platform_config.history(field_id=field_id, limit=limit, tenant_id=tenant.id)})
