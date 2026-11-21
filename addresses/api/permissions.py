from rest_framework.permissions import BasePermission, IsAuthenticated

from access.authorization.platform import is_platform_superuser


class IsAddressOwnerOrReadOnlyStaff(BasePermission):
    """
    Authenticated users manage their own addresses.
    Platform superusers may read any address when ADDRESSES_SUPPORT_STAFF_READ_ONLY
    is enabled (``is_staff`` alone grants nothing in the API).
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if obj.user_id == request.user.id:
            return True
        if request.method in ("GET", "HEAD", "OPTIONS") and is_platform_superuser(request.user):
            from django.conf import settings
            return getattr(settings, "ADDRESSES_SUPPORT_STAFF_READ_ONLY", True)
        return False


class IsAuthenticatedOwner(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class IsAdminUserOrReadOnly(BasePermission):
    """Reads for any signed-in user; writes for platform superusers only."""

    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return bool(request.user and request.user.is_authenticated)
        return is_platform_superuser(request.user)
