import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class OrderType(models.TextChoices):
    DELIVERY = "delivery", "Delivery"
    PICKUP = "pickup", "Pickup"
    DINE_IN = "dine_in", "Dine In"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    CARD = "card", "Card"
    ONLINE = "online", "Online"
    WALLET = "wallet", "Wallet"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "accepted", "Accepted"
    PREPARING = "preparing", "Preparing"
    READY = "ready", "Ready"
    SERVED = "served", "Served"
    DELIVERED = "delivered", "Delivered"
    COMPLETED = "completed", "Completed"
    PICKED_UP = "picked_up", "Picked Up"
    CANCELLED = "cancelled", "Cancelled"


class Order(models.Model):
    """
    Main customer order for a specific branch.

    Key changes vs. the previous version:
    - customer/user is nullable (guest checkout support).
    - tenant was removed in favor of branch (tenant is reachable via branch.tenant).
    - delivery_address is a FK to Address (the user's address book), not an
      embedded JSON snapshot. NOTE: because this is a live FK, editing the
      referenced Address later will change what past orders display, and the
      Address can't be deleted while any order still references it
      (on_delete=PROTECT). If historical accuracy matters, consider adding
      snapshot fields alongside this FK later.
    - order_number is a unique, human-readable identifier for display purposes
      (separate from the pk). Its value should be generated in the
      Service/BLL layer, not here.
    - tax is a snapshot decimal amount, but the value/rate it's derived from
      lives on Tenant (branch.tenant.tax). The Service layer is responsible
      for reading branch.tenant.tax and computing this field at order
      creation time — Order.tax should not be edited directly afterwards.
    - service_charge is a mandatory restaurant-added service fee (e.g. a
      fixed % automatically applied to dine-in bills), NOT a voluntary tip
      left by the customer. If you also need customer tips, that should be
      a separate field (e.g. `tip`).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Primary key; safe to expose to the client",
    )

    order_number = models.CharField(
        max_length=50,
        unique=True,
        help_text=(
            "Human-readable order number (e.g. ORD-20260718-0001). "
            "Should be generated in the Service/BLL layer."
        ),
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        help_text="Nullable to support guest checkout",
    )

    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.PROTECT,
        related_name="orders",
    )

    order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
    )

    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )

    delivery_address = models.ForeignKey(
        "OrderDeliveryAddress",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
        help_text=(
            "Immutable delivery address snapshot. Only set when "
            "order_type == delivery."
        ),
    )

    table_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Required only for dine-in orders",
    )

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)

    tax = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=(
            "Snapshot tax amount. Computed in the Service layer from "
            "branch.tenant.tax at order creation time; do not edit directly."
        ),
    )

    service_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=(
            "Mandatory restaurant-added service fee (not a customer tip)."
        ),
    )

    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    discount_code = models.CharField(max_length=50, blank=True)

    # What the customer saw: the order is paid in the business currency
    # (Tenant.currency, the amounts above); these record the currency the
    # customer chose to view prices in and the rates used, at order time.
    currency = models.CharField(max_length=10, blank=True, default="")
    display_currency = models.CharField(max_length=10, blank=True, default="")
    display_total = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    exchange_rates = models.JSONField(default=dict, blank=True)

    notes = models.TextField(blank=True)

    estimated_time = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Estimated preparation/delivery time in minutes",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.order_number} - {self.branch}"

    class Meta:
        db_table = "order"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order_number"]),
            models.Index(fields=["customer"]),
            models.Index(fields=["branch"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["branch", "created_at"]),
        ]


class OrderItem(models.Model):
    """
    A single line item of an order.

    name/image/unit_price are snapshots taken at order time (intentional
    denormalization), so later menu changes don't affect past orders.
    extras is back to a relation (OrderItemExtra) rather than JSON, so each
    selected extra is its own snapshotted row.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    menu_item = models.ForeignKey(
        "menu.MenuItem",
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    name = models.CharField(
        max_length=255,
        help_text="Snapshot of the menu item's name at order time",
    )

    image = models.CharField(
        max_length=500,
        blank=True,
        help_text="Snapshot of the menu item's image URL at order time",
    )

    quantity = models.PositiveIntegerField(default=1)

    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Snapshot of the menu item's price at order time",
    )

    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text=(
            "quantity * unit_price + sum of extras' prices; computed and set "
            "in the Service layer (see calculate_total_price)."
        ),
    )

    notes = models.TextField(blank=True)

    def calculate_total_price(self) -> Decimal:
        """
        Calculates total_price from unit_price/quantity/extras.
        This is just a helper; calling it (and setting self.total_price)
        should happen in the Service/BLL layer when creating/editing an
        OrderItem. Requires self.extras to already be saved (needs self.pk).
        """
        extras_total = sum((e.price for e in self.extras.all()), Decimal("0"))
        return (self.unit_price * self.quantity) + extras_total

    def __str__(self):
        return f"{self.quantity}x {self.name}"

    class Meta:
        db_table = "order_item"
        indexes = [
            models.Index(fields=["order"]),
            models.Index(fields=["menu_item"]),
        ]


class OrderItemExtra(models.Model):
    """
    Snapshot of a selected Extra for a given OrderItem; the price is stored
    at order time (independent of later Extra/MenuItemExtra price changes).
    """

    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        related_name="extras",
    )

    extra = models.ForeignKey(
        "menu.Extra",
        on_delete=models.PROTECT,
        related_name="order_item_links",
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Snapshot of the extra's price at order time",
    )

    def __str__(self):
        return f"{self.extra.name} (+{self.price})"

    class Meta:
        db_table = "order_item_extra"
        unique_together = ("order_item", "extra")


class OrderStatusHistory(models.Model):
    """
    Order status change history; a record should be created here (in the
    Service layer, not via signals) every time an order's status changes.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_history",
    )

    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
    )

    timestamp = models.DateTimeField(auto_now_add=True)

    note = models.TextField(blank=True)

    def __str__(self):
        return f"Order {self.order_id} -> {self.status} @ {self.timestamp}"

    class Meta:
        db_table = "order_status_history"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["order"]),
        ]


class OrderDeliveryAddress(models.Model):
    """
    Immutable delivery address snapshot attached to an order.

    Created at checkout from either a user address-book entry (address_id)
    or inline guest delivery fields. Never updated after creation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_address_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Optional reference to the user address book entry that was snapshotted.",
    )

    title = models.CharField(max_length=100, blank=True, default="")
    label = models.CharField(max_length=20, blank=True, default="")
    first_name = models.CharField(max_length=64, blank=True, default="")
    last_name = models.CharField(max_length=64, blank=True, default="")
    company = models.CharField(max_length=128, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    country_code = models.CharField(max_length=5, blank=True, default="")
    country = models.CharField(max_length=2, blank=True, default="")
    province = models.CharField(max_length=100, blank=True, default="")
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=100, blank=True, default="")
    street = models.CharField(max_length=500)
    building_number = models.CharField(max_length=32, blank=True, default="")
    unit = models.CharField(max_length=32, blank=True, default="")
    postal_code = models.CharField(max_length=20, blank=True, default="")

    latitude = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    delivery_notes = models.TextField(blank=True, default="")
    formatted_address = models.TextField(blank=True, default="")
    floor = models.CharField(max_length=32, blank=True, default="")
    address_type = models.CharField(max_length=20, blank=True, default="")

    # Immutable delivery metadata captured at checkout
    branch_id = models.UUIDField(null=True, blank=True)
    delivery_zone = models.CharField(max_length=128, blank=True, default="")
    verification_status = models.CharField(max_length=20, blank=True, default="pending")
    distance_km = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estimated_delivery_time = models.PositiveIntegerField(null=True, blank=True)
    calculated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.street}, {self.city}"

    class Meta:
        db_table = "order_delivery_address"
        indexes = [
            models.Index(fields=["source_address_id"], name="order_del_addr_source_idx"),
            models.Index(fields=["created_at"], name="order_del_addr_created_idx"),
        ]
