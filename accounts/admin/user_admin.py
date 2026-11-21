from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from accounts.models import User, OTPCode
from accounts.services import superuser_bll
from accounts.services.profile_bll import AccountRestoreConflict, ProfileBusinessLogicLayer
from core.exceptions.account import AccountAlreadyDeletedException


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = [
        "phone_number", "email", "full_name",
        "is_verified", "is_active", "is_superuser", "is_deleted", "created_at",
    ]
    list_filter = ["is_active", "is_superuser", "is_verified", "is_deleted"]
    search_fields = [
        "phone_number", "email", "first_name", "last_name",
        "deleted_phone_number", "deleted_email",
    ]
    ordering = ["-created_at"]
    # Superuser status changes only through Superuser requests (approve) and
    # the "Revoke superuser" action, so every change is checked and recorded.
    readonly_fields = [
        "id", "is_superuser", "is_staff", "created_at", "updated_at",
        "is_deleted", "deleted_at", "deleted_phone_number", "deleted_email",
    ]
    actions = ["soft_delete_selected_users", "restore_selected_users", "revoke_superuser"]

    def get_queryset(self, request):
        return User.all_objects.all()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Soft-delete selected accounts")
    def soft_delete_selected_users(self, request, queryset):
        for user in queryset:
            try:
                ProfileBusinessLogicLayer.soft_delete(user)
            except AccountAlreadyDeletedException:
                continue

    @admin.action(description="Restore selected deleted accounts")
    def restore_selected_users(self, request, queryset):
        done = 0
        for user in queryset.filter(is_deleted=True):
            try:
                ProfileBusinessLogicLayer.restore(user)
                done += 1
            except AccountRestoreConflict as exc:
                self.message_user(request, f"{user.id}: {exc}", messages.ERROR)
        if done:
            self.message_user(request, f"Restored {done} account(s).", messages.SUCCESS)

    @admin.action(description="Revoke superuser (and Django admin access)")
    def revoke_superuser(self, request, queryset):
        done = 0
        for user in queryset.filter(is_superuser=True):
            try:
                superuser_bll.revoke(user, actor=request.user)
                done += 1
            except superuser_bll.SuperuserError as exc:
                self.message_user(request, f"{user}: {exc}", messages.ERROR)
        if done:
            self.message_user(request, f"Revoked superuser from {done} account(s).", messages.SUCCESS)

    fieldsets = (
        (None, {"fields": ("id", "country_code", "phone_number", "email", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name", "avatar")}),
        ("Status", {"fields": ("is_verified",)}),
        ("Deletion", {"fields": ("is_deleted", "deleted_at", "deleted_phone_number", "deleted_email")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("phone_number", "email", "password1", "password2"),
        }),
    )


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = [
        "identifier", "otp_type", "code", "attempts",
        "is_used", "is_valid", "expires_at", "created_at",
    ]
    list_filter = ["otp_type", "is_used"]
    search_fields = ["identifier"]
    ordering = ["-created_at"]
    readonly_fields = ["id", "created_at"]