from django.apps import AppConfig


class PlatformSettingsConfig(AppConfig):
    """Platform-wide settings edited by superusers (homepage hero, ...)."""

    name = "platform_settings"
    default_auto_field = "django.db.models.BigAutoField"
