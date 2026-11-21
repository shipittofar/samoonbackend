# project/urls.py
from django.contrib import admin
from django.urls import path, include
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.decorators import api_view, renderer_classes
from rest_framework.renderers import BrowsableAPIRenderer, JSONRenderer
from rest_framework.response import Response
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)


def list_urls(patterns, prefix=""):
    urls = []
    for pattern in patterns:
        if isinstance(pattern, URLPattern):
            full_path = prefix + str(pattern.pattern)
            if not full_path.startswith("admin"):
                urls.append(full_path)
        elif isinstance(pattern, URLResolver):
            new_prefix = prefix + str(pattern.pattern)
            urls.extend(list_urls(pattern.url_patterns, new_prefix))
    return urls


@api_view(["GET"])
@renderer_classes([BrowsableAPIRenderer, JSONRenderer])
def api_root(request, format=None):
    from django.urls import get_resolver

    resolver = get_resolver()
    all_urls = sorted(set(list_urls(resolver.url_patterns)))

    grouped = {}
    for u in all_urls:
        full_path = f"/{u}"
        segments = full_path.strip("/").split("/")
        group = segments[0] if segments[0] else "root"

        if "<" in full_path:
            value = full_path
        else:
            value = request.build_absolute_uri(full_path)

        grouped.setdefault(group, {})[full_path] = value

    return Response({
        "docs": request.build_absolute_uri("/api/docs/"),
        "schema": request.build_absolute_uri("/api/schema/"),
        "endpoints": grouped,
    })


urlpatterns = [
    path("", api_root, name="api-root"),

    path('admin/', admin.site.urls),

    path('api/core/', include('core.api.urls')),

    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema')),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema')),

    path('qr/<slug:code>/', include(('tenants.api.urls_qr', 'qr'), namespace='qr')),
    path('api/public/', include('tenants.api.urls_public', namespace='public')),
    path('api/tenants/', include('tenants.api.urls', namespace='tenants')),
    # Platform superuser console API
    path('api/superadmin/', include('superadmin.api.urls', namespace='superadmin')),
    path('api/branches/', include('tenants.api.urls_branches', namespace='branches')),
    path('api/menu/', include('menu.api.urls', namespace='menu')),

    path('api/uploads/', include(('uploads.api.urls', 'uploads'), namespace='uploads')),
    path('api/orders/', include('orders.api.urls', namespace='orders')),
    path('api/reservations/', include('reservations.api.urls', namespace='reservations')),

    path('api/auth/', include('accounts.api.urls', namespace='accounts')),
    path('api/users/', include('accounts.api.urls_users', namespace='users')),
    path('api/permissions/', include('access.api.urls_permissions', namespace='access-permissions')),
    path('api/authorization/', include('access.api.urls', namespace='access')),
    # Compatibility aliases — same views as /api/authorization/ (no duplicated logic).
    path('api/access/', include(('access.api.urls', 'access'), namespace='access-compat')),
]