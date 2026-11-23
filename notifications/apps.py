from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """In-app notifications created from server-side events (orders,
    reservations, business requests, staff, account security)."""

    name = "notifications"
    default_auto_field = "django.db.models.BigAutoField"
