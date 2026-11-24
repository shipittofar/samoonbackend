"""Settlement with business owners.

Money flow (all through wallet.services.post, double-entry):

* wallet-paid order: customer -> business_pending (at order time)
* order done (served / delivered / picked up / completed): an
  OrderSettlement row snapshots the commission rate; commission moves
  business_pending -> system_revenue (wallet orders) or business -> system_revenue
  (cash / card orders: the business now owes it and it is netted later)
* hold period over: business_pending -> business (available)
* payout requested: business -> business_reserved
* superuser paid it: business_reserved -> system_payout
* rejected / cancelled: business_reserved -> business
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class TenantSettlementTerms(models.Model):
    """A business's own commission rate and hold period; empty = platform default."""

    tenant = models.OneToOneField("tenants.Tenant", on_delete=models.CASCADE, related_name="settlement_terms")
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    hold_days = models.PositiveSmallIntegerField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"terms {self.tenant_id}"


class SettlementStatus(models.TextChoices):
    HELD = "held", "On hold"
    RELEASED = "released", "Available"
    CHARGED = "charged", "Commission charged (paid outside the wallet)"


class OrderSettlement(models.Model):
    """One row per finished order: what the business earns and what the
    platform takes. Created once, when the order first reaches a done state."""

    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="settlement")
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="order_settlements")
    currency = models.CharField(max_length=10)
    gross = models.DecimalField(max_digits=20, decimal_places=4)
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2)
    commission = models.DecimalField(max_digits=20, decimal_places=4)
    net = models.DecimalField(max_digits=20, decimal_places=4)
    via_wallet = models.BooleanField()
    status = models.CharField(max_length=10, choices=SettlementStatus.choices, db_index=True)
    completed_at = models.DateTimeField()
    release_after = models.DateTimeField(null=True, blank=True, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)
    commission_tx = models.OneToOneField(
        "wallet.LedgerTransaction", null=True, blank=True, on_delete=models.PROTECT, related_name="commission_for"
    )
    release_tx = models.OneToOneField(
        "wallet.LedgerTransaction", null=True, blank=True, on_delete=models.PROTECT, related_name="release_for"
    )

    class Meta:
        ordering = ["-completed_at"]
        indexes = [models.Index(fields=["tenant", "-completed_at"])]

    def __str__(self) -> str:
        return f"{self.order_id} {self.net} {self.currency} {self.status}"


class PayoutAccountKind(models.TextChoices):
    IBAN = "iban", "Bank account (Sheba)"
    CRYPTO = "crypto", "Crypto wallet"


class PayoutAccountStatus(models.TextChoices):
    PENDING = "pending", "Waiting for approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    DISABLED = "disabled", "Disabled"


class PayoutAccount(models.Model):
    """Where a business wants its money. Never edited: a change is a new
    account, which a superuser approves before any payout can go to it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="payout_accounts")
    kind = models.CharField(max_length=10, choices=PayoutAccountKind.choices)
    currency = models.CharField(max_length=10)
    # IBAN: "IR" + 24 digits. Crypto: coin key (USDT_TRC20, TON...) + address.
    iban = models.CharField(max_length=26, blank=True)
    holder_name = models.CharField(max_length=120, blank=True)
    bank_name = models.CharField(max_length=80, blank=True)
    asset = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=120, blank=True)
    memo = models.CharField(max_length=60, blank=True)
    label = models.CharField(max_length=80, blank=True)
    is_default = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=PayoutAccountStatus.choices, default=PayoutAccountStatus.PENDING, db_index=True)
    review_note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} {self.iban or self.address} ({self.status})"


class PayoutStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    PAID = "paid", "Paid"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class Payout(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="payouts")
    account = models.ForeignKey(PayoutAccount, on_delete=models.PROTECT, related_name="payouts")
    currency = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    status = models.CharField(max_length=10, choices=PayoutStatus.choices, default=PayoutStatus.REQUESTED, db_index=True)
    # Created by the weekly schedule rather than the owner.
    automatic = models.BooleanField(default=False)
    # Bank tracking number / transaction hash, entered by the superuser who paid.
    reference = models.CharField(max_length=200, blank=True)
    note = models.CharField(max_length=300, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    hold_tx = models.OneToOneField("wallet.LedgerTransaction", on_delete=models.PROTECT, related_name="payout_hold_for")
    close_tx = models.OneToOneField(
        "wallet.LedgerTransaction", null=True, blank=True, on_delete=models.PROTECT, related_name="payout_close_for"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.amount} {self.currency} {self.status}"
