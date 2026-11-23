from django.apps import AppConfig


class WalletConfig(AppConfig):
    """Customer wallets on a double-entry ledger (see wallet/models.py)."""

    name = "wallet"
    default_auto_field = "django.db.models.BigAutoField"
