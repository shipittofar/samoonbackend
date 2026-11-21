from django.contrib import admin, messages

from accounts.models import PlatformSecuritySettings, SuperuserRequest, SuperuserRequestStatus
from accounts.services import superuser_bll


def _superuser_only_admin(request) -> bool:
    """The Django admin is for platform superusers only. ``is_staff`` alone no
    longer opens it: with model permissions handed out through groups, a staff
    account could otherwise edit other users."""
    user = request.user
    return bool(user and user.is_active and user.is_superuser)


admin.site.has_permission = _superuser_only_admin


@admin.register(PlatformSecuritySettings)
class PlatformSecuritySettingsAdmin(admin.ModelAdmin):
    list_display = ["__str__", "allow_superuser_requests", "updated_at", "updated_by"]
    fields = ["allow_superuser_requests", "updated_at", "updated_by"]
    readonly_fields = ["updated_at", "updated_by"]

    def has_add_permission(self, request):
        return not PlatformSecuritySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        PlatformSecuritySettings.load()
        return super().changelist_view(request, extra_context)

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SuperuserRequest)
class SuperuserRequestAdmin(admin.ModelAdmin):
    list_display = ["user", "status", "note", "requested_at", "decided_by", "decided_at"]
    list_filter = ["status"]
    search_fields = ["user__phone_number", "user__email", "user__first_name", "user__last_name"]
    readonly_fields = ["id", "user", "status", "note", "requested_at", "decided_by", "decided_at"]
    actions = ["approve_selected", "reject_selected"]

    # Requests come only from `samoon admin-add`; decisions only via the actions.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def _decide(self, request, queryset, decide, verb):
        done = 0
        for item in queryset.filter(status=SuperuserRequestStatus.PENDING):
            try:
                decide(item, actor=request.user)
                done += 1
            except superuser_bll.SuperuserError as exc:
                self.message_user(request, f"{item.user}: {exc}", messages.ERROR)
        if done:
            self.message_user(request, f"{verb} {done} request(s).", messages.SUCCESS)

    @admin.action(description="Approve selected requests (make superuser)")
    def approve_selected(self, request, queryset):
        self._decide(request, queryset, superuser_bll.approve, "Approved")

    @admin.action(description="Reject selected requests")
    def reject_selected(self, request, queryset):
        self._decide(request, queryset, superuser_bll.reject, "Rejected")
