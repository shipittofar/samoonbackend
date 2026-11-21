from rest_framework.permissions import BasePermission

from access.authorization.platform import is_platform_superuser


class IsPlatformSuperuser(BasePermission):
    message = "Platform superusers only."

    def has_permission(self, request, view) -> bool:
        return is_platform_superuser(request.user)
