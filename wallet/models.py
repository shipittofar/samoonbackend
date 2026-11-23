"""Wallet: a double-entry ledger.

- Every money movement is one LedgerTransaction with two or more
  LedgerEntry rows whose amounts sum to zero (per currency). Entries are
  never edited or deleted; a mistake is corrected by a reversing transaction.
- WalletAccount.balance is a cache of SUM(entries.amount) for that account,
  updated in the same database transaction as the entries, under a row lock
  (``select_for_update``) — so concurrent payments cannot overspend. The
  ``wallet_check`` command verifies the cache against the entries.
- Accounts: one per (customer user, currency) and per (business, currency),
  plus platform system accounts (top-ups in, manual adjustments) that are
  the other side of money entering or leaving customer wallets.
"""
import uuid

from django.conf import settings
from django.db import models


class AccountKind(models.TextChoices):
    CUSTOMER = "customer", "Customer wallet"
    BUSINESS = "business", "Business (payable to owner)"
    SYSTEM_TOPUP = "system_topup", "System: top-ups received"
    SYSTEM_ADJUSTMENT = "system_adjustment", "System: manual adjustments"


class WalletAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=AccountKind.choices, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="wallet_accounts"
    )
    tenant = models.ForeignKey("tenants.Tenant", null=True, blank=True, on_delete=models.PROTECT, related_name="wallet_accounts")
    currency = models.CharField(max_length=10)
    balance = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    # Customer accounts can never go below zero; system accounts can.
    allow_negative = models.BooleanField(default=False)
    is_frozen = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "currency"], condition=models.Q(kind="customer"), name="uniq_customer_wallet"
            ),
            models.UniqueConstraint(
                fields=["tenant", "currency"], condition=models.Q(kind="business"), name="uniq_business_wallet"
            ),
            models.UniqueConstraint(
                fields=["kind", "currency"],
                condition=models.Q(kind__in=["system_topup", "system_adjustment"]),
                name="uniq_system_wallet",
            ),
            models.CheckConstraint(
                condition=models.Q(allow_negative=True) | models.Q(balance__gte=0), name="wallet_non_negative"
            ),
        ]
        indexes = [models.Index(fields=["user", "currency"])]

    def __str__(self) -> str:
        owner = self.user_id or self.tenant_id or self.kind
        return f"{self.kind}:{owner}:{self.currency}"


class TransactionKind(models.TextChoices):
    ORDER_PAYMENT = "order_payment", "Order payment"
    ORDER_REFUND = "order_refund", "Order refund"
    TOPUP = "topup", "Top-up"
    ADJUSTMENT = "adjustment", "Manual adjustment"
    REVERSAL = "reversal", "Reversal"


class LedgerTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=TransactionKind.choices, db_index=True)
    currency = models.CharField(max_length=10)
    # Same key twice = the same operation: the second call returns the first
    # transaction instead of moving money again.
    idempotency_key = models.CharField(max_length=120, unique=True)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="wallet_transactions")
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )
    description = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} {self.currency} {self.id}"


class LedgerEntry(models.Model):
    transaction = models.ForeignKey(LedgerTransaction, on_delete=models.PROTECT, related_name="entries")
    account = models.ForeignKey(WalletAccount, on_delete=models.PROTECT, related_name="entries")
    # Positive = into the account, negative = out of it.
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    balance_after = models.DecimalField(max_digits=20, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["account", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.account_id} {self.amount}"


class TopUpStatus(models.TextChoices):
    CREATED = "created", "Created"          # row exists, gateway not called yet
    PENDING = "pending", "Waiting for payment"
    PAID = "paid", "Paid (wallet credited)"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled by the payer"
    EXPIRED = "expired", "Expired"


class TopUpMethod(models.TextChoices):
    BANK = "bank", "Iranian bank gateway"
    CRYPTO = "crypto", "Cryptocurrency"


class TopUp(models.Model):
    """One attempt to add money to a wallet through a gateway.

    The wallet is credited only after the gateway itself confirms the payment
    to the server (bank: verify call; crypto: signed webhook / status check),
    never because the browser came back to a "success" URL. Crediting goes
    through wallet.services.credit_topup with this row's id as the key, so a
    repeated callback or webhook can never credit twice.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="topups")
    method = models.CharField(max_length=10, choices=TopUpMethod.choices)
    provider = models.CharField(max_length=20, db_index=True)
    # What the wallet receives.
    currency = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=20, decimal_places=8)
    # Crypto: coin+network key (USDT_TRC20, TON...). Bank: empty.
    asset = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=TopUpStatus.choices, default=TopUpStatus.CREATED, db_index=True)
    # Gateway references: authority / token / RefId / invoice id.
    gateway_ref = models.CharField(max_length=120, blank=True, db_index=True)
    # Bank: reference / tracking number shown to the payer; crypto: tx hash.
    receipt_ref = models.CharField(max_length=200, blank=True)
    card_pan = models.CharField(max_length=30, blank=True)
    failure_reason = models.CharField(max_length=300, blank=True)
    # The gateway (or a superuser, for direct transfers) confirmed the money arrived.
    verified = models.BooleanField(default=False)
    # What was credited; can be less than ``amount`` when a crypto payer underpaid.
    credited_amount = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_topups"
    )
    ledger_transaction = models.OneToOneField(
        LedgerTransaction, null=True, blank=True, on_delete=models.PROTECT, related_name="topup"
    )
    # Short numeric id for gateways that need an integer order id (Mellat, Sadad).
    order_number = models.BigIntegerField(unique=True)
    gateway_log = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"]), models.Index(fields=["provider", "gateway_ref"])]

    def __str__(self) -> str:
        return f"{self.provider} {self.amount} {self.currency} {self.status}"

    def log(self, event: str, data) -> None:
        """Append a gateway exchange (secrets are never logged)."""
        from django.utils import timezone

        entry = {"at": timezone.now().isoformat(), "event": event, "data": data}
        self.gateway_log = [*(self.gateway_log or [])[-40:], entry]

