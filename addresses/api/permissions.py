from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated

from accounts.models import UserRole


class IsAddressOwnerOrReadOnlyStaff(BasePermission):
    """
    Authenticated users manage their own addresses.
    Django staff (support) may read any address when ADDRESSES_SUPPORT_STAFF_READ_ONLY is enabled.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if obj.user_id == request.user.id:
            return True
        if request.method in ("GET", "HEAD", "OPTIONS") and request.user.is_staff:
            from django.conf import settings
            return getattr(settings, "ADDRESSES_SUPPORT_STAFF_READ_ONLY", True)
        if request.user.is_staff and getattr(request.user, "role", None) == UserRole.ADMIN:
            return request.method in ("GET", "HEAD", "OPTIONS")
        return False


class IsAuthenticatedOwner(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class IsAdminUserOrReadOnly(IsAdminUser):
    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return request.user and request.user.is_authenticated
        return super().has_permission(request, view)
