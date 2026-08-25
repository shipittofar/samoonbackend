from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from accounts.models import User, OTPCode


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = [
        "phone_number", "email", "full_name", "role",
        "is_verified", "is_active", "is_staff", "created_at",
    ]
    list_filter = ["is_active", "is_staff", "is_verified", "role"]
    search_fields = ["phone_number", "email", "first_name", "last_name"]
    ordering = ["-created_at"]
    readonly_fields = ["id", "created_at", "updated_at"]

    fieldsets = (
        (None, {"fields": ("id", "country_code", "phone_number", "email", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name", "avatar")}),
        ("Status", {"fields": ("role", "is_verified")}),
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