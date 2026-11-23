from django.apps import AppConfig


class CurrenciesConfig(AppConfig):
    """Currencies, superuser-managed exchange rates and price conversion."""

    name = "currencies"
    default_auto_field = "django.db.models.BigAutoField"
