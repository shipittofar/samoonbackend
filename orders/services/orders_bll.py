# orders/services/orders_bll.py
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

from django.db import transaction

from addresses.services.address_domain_service import AddressDomainService
from orders.selectors import OrdersDataAccessLayer
from orders.models import Order, OrderItemExtra, OrderStatus, OrderType, PaymentMethod
from core.exceptions import (
    AddressNotFoundException,
    BranchNotFoundException,
    CashOnDeliveryNotEnabledException,
    DeliveryAddressRequiredException,
    ExtraNotAvailableException,
    InvalidDiscountCodeException,
    InvalidOrderStatusTransitionException,
    MenuItemNotFoundException,
    MenuItemNotInTenantException,
    MenuItemUnavailableException,
    MinimumOrderNotMetException,
    NotTenantOwnerException,
    OrderingDisabledException,
    OrderNotCancellableException,
    OrderNotEditableException,
    OrderNotFoundException,
    OrderTypeNotEnabledException,
    PaymentMethodNotEnabledException,
    TableNumberRequiredException,
    TenantNotFoundException,
)
from notifications import events as notification_events
from orders.ws.notifications import (
    notify_order_status_change,
    schedule_console_order_changed,
)


CANCELLABLE_STATUSES = {OrderStatus.PENDING, OrderStatus.CONFIRMED}

STATUS_TRANSITIONS = {
    OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {
        OrderStatus.SERVED,
        OrderStatus.DELIVERED,
        OrderStatus.PICKED_UP,
        OrderStatus.COMPLETED,
    },
    OrderStatus.DELIVERED: {OrderStatus.COMPLETED},
    OrderStatus.SERVED: set(),
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


class OrdersBusinessLogicLayer:
    """
    Order creation/editing rules: validation, price snapshotting,
    tax/service-charge/discount calculation. Talks to the database only
    through the DAL.
    """

    def __init__(
        self,
        dal: Optional[OrdersDataAccessLayer] = None,
        address_bll: Optional[AddressDomainService] = None,
    ):
        self.dal = dal or OrdersDataAccessLayer()
        self.address_domain = address_bll or AddressDomainService()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_order(self, *, customer, validated_data: dict) -> Order:
        branch = self._get_active_branch(validated_data["branch_id"])
        tenant = branch.tenant
        order_type = validated_data["order_type"]

        self._validate_order_type_requirements(order_type, validated_data)
        self._validate_branch_checkout(
            branch,
            order_type=order_type,
            payment_method=validated_data["payment_method"],
        )

        items_data = validated_data["items"]
        menu_items_by_id = self._load_and_validate_menu_items(
            tenant, items_data)

        discount_amount = self._resolve_discount(
            tenant, validated_data.get("discount_code", "")
        )

        with transaction.atomic():
            delivery_address = None
            if order_type == OrderType.DELIVERY:
                delivery_address = self._resolve_delivery_address_snapshot(
                    customer, validated_data["delivery_address"], branch
                )

            order = self.dal.create_order(
                order_number=self._generate_order_number(),
                customer=customer,
                branch=branch,
                order_type=order_type,
                payment_method=validated_data["payment_method"],
                status=OrderStatus.PENDING,
                table_number=validated_data.get("table_number") or None,
                delivery_address=delivery_address,
                discount_code=validated_data.get("discount_code", ""),
                notes=validated_data.get("notes", ""),
            )

            subtotal = self._create_items_and_extras(
                order, items_data, menu_items_by_id)
            self._validate_minimum_order(branch, subtotal)
            self._apply_totals(order, tenant, order_type,
                               subtotal, discount_amount)
            order.refresh_from_db()
            from currencies.services import snapshot_order

            snapshot_order(order, validated_data.get("display_currency"))

            self.dal.create_status_history(order, OrderStatus.PENDING)
            schedule_console_order_changed(order)
            notification_events.order_created(order)

        return self.dal.get_order_by_id(order.id)

    # ------------------------------------------------------------------
    # List / retrieve
    # ------------------------------------------------------------------
    def list_orders_for_customer(self, customer):
        return self.dal.get_orders_for_customer(customer.id)

    def get_order_detail(self, customer, public_id: UUID) -> Order:
        order = self.dal.get_order_by_public_id_for_customer(
            public_id, customer.id)
        if order is None:
            raise OrderNotFoundException()
        return order

    # ------------------------------------------------------------------
    # Update (reorder)
    # ------------------------------------------------------------------
    def update_order(self, *, customer, public_id: UUID, validated_data: dict) -> Order:
        branch = self._get_active_branch(validated_data["branch_id"])
        tenant = branch.tenant
        order_type = validated_data["order_type"]

        self._validate_order_type_requirements(order_type, validated_data)
        self._validate_branch_checkout(
            branch,
            order_type=order_type,
            payment_method=validated_data["payment_method"],
        )

        items_data = validated_data["items"]
        menu_items_by_id = self._load_and_validate_menu_items(
            tenant, items_data)

        discount_amount = self._resolve_discount(
            tenant, validated_data.get("discount_code", "")
        )

        with transaction.atomic():
            order = self.dal.get_order_by_public_id_for_update(public_id)
            if order is None or order.customer_id != customer.id:
                raise OrderNotFoundException()

            if order.status != OrderStatus.PENDING:
                raise OrderNotEditableException()

            self.dal.delete_order_items(order)

            delivery_address = None
            if order_type == OrderType.DELIVERY:
                delivery_address = self._resolve_delivery_address_snapshot(
                    customer, validated_data["delivery_address"], branch
                )

            self.dal.update_order_fields(
                order,
                branch=branch,
                order_type=order_type,
                payment_method=validated_data["payment_method"],
                table_number=validated_data.get("table_number") or None,
                delivery_address=delivery_address,
                discount_code=validated_data.get("discount_code", ""),
                notes=validated_data.get("notes", ""),
            )

            subtotal = self._create_items_and_extras(
                order, items_data, menu_items_by_id)
            self._validate_minimum_order(branch, subtotal)
            self._apply_totals(order, tenant, order_type,
                               subtotal, discount_amount)

        return self.dal.get_order_by_id(order.id)

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------
    def cancel_order(self, *, customer, public_id: UUID) -> Order:
        with transaction.atomic():
            order = self.dal.get_order_by_public_id_for_update(public_id)
            if order is None or order.customer_id != customer.id:
                raise OrderNotFoundException()

            if order.status == OrderStatus.CANCELLED:
                return order

            if order.status not in CANCELLABLE_STATUSES:
                raise OrderNotCancellableException()

            self.dal.update_order_fields(order, status=OrderStatus.CANCELLED)
            self.dal.create_status_history(
                order, OrderStatus.CANCELLED, note="Cancelled by customer"
            )
            schedule_console_order_changed(order)
            transaction.on_commit(lambda: notify_order_status_change(order))
            notification_events.order_status_changed(order, actor=customer)

        return self.dal.get_order_by_id(order.id)

    def admin_cancel_order(self, *, order: Order) -> Order:
        """Cancel an order from Django Admin without requiring the customer actor."""
        with transaction.atomic():
            locked = self.dal.get_order_by_public_id_for_update(order.id)
            if locked is None:
                raise OrderNotFoundException()
            if locked.status == OrderStatus.CANCELLED:
                return locked
            allowed_next = STATUS_TRANSITIONS.get(locked.status, set())
            if OrderStatus.CANCELLED not in allowed_next:
                raise OrderNotCancellableException()
            self.dal.update_order_fields(locked, status=OrderStatus.CANCELLED)
            self.dal.create_status_history(
                locked, OrderStatus.CANCELLED, note="Cancelled in Django Admin"
            )
            schedule_console_order_changed(locked)
            transaction.on_commit(lambda: notify_order_status_change(locked))
            notification_events.order_status_changed(locked)
        return self.dal.get_order_by_id(locked.id)

    # ------------------------------------------------------------------
    # Status update (tenant owner only)
    # ------------------------------------------------------------------
    def update_order_status(self, *, user, public_id: UUID, new_status: str) -> Order:
        with transaction.atomic():
            order = self.dal.get_order_by_public_id_for_update(public_id)
            if order is None:
                raise OrderNotFoundException()

            if order.branch.tenant.owner.user.id != user.id:
                raise NotTenantOwnerException()

            allowed_next_statuses = STATUS_TRANSITIONS.get(order.status, set())
            if new_status not in allowed_next_statuses:
                raise InvalidOrderStatusTransitionException(
                    f"Cannot move order from '{order.status}' to '{new_status}'."
                )

            if (
                    new_status == OrderStatus.DELIVERED
                    and order.order_type != OrderType.DELIVERY
            ):
                raise InvalidOrderStatusTransitionException(
                    "Only delivery orders can be marked as out for delivery."
                )

            if (
                    new_status == OrderStatus.PICKED_UP
                    and order.order_type != OrderType.PICKUP
            ):
                raise InvalidOrderStatusTransitionException(
                    "Only pickup orders can be marked as picked up."
                )

            if (
                    new_status == OrderStatus.SERVED
                    and order.order_type != OrderType.DINE_IN
            ):
                raise InvalidOrderStatusTransitionException(
                    "Only dine-in orders can be marked as served."
                )

            if (
                    new_status == OrderStatus.COMPLETED
                    and order.order_type == OrderType.DINE_IN
            ):
                raise InvalidOrderStatusTransitionException(
                    "Dine-in orders are final once served."
                )

            self.dal.update_order_fields(order, status=new_status)
            self.dal.create_status_history(order, new_status)
            schedule_console_order_changed(order)
            transaction.on_commit(lambda: notify_order_status_change(order))
            notification_events.order_status_changed(order, actor=user)

        return self.dal.get_order_by_id(order.id)

    def list_orders_for_console(
        self,
        *,
        user,
        tenant_id: UUID,
        branch_id: UUID,
    ):
        branch = self.dal.get_branch_for_console(
            tenant_id=tenant_id,
            branch_id=branch_id,
        )
        if branch is None:
            raise BranchNotFoundException()

        self._assert_console_tenant_owner(user=user, tenant=branch.tenant)

        return self.dal.list_orders_for_console(
            tenant_id=tenant_id,
            branch_id=branch_id,
        )

    def get_pending_order_count(
        self,
        *,
        user,
        tenant_id: UUID,
        branch_id: UUID,
    ) -> int:
        from access.authorization.console_workspace import (
            ORDERS_CONSOLE_PERMISSIONS,
            authorize_console_branch,
        )

        authorize_console_branch(
            user=user,
            tenant_id=tenant_id,
            branch_id=branch_id,
            permission_slugs=ORDERS_CONSOLE_PERMISSIONS,
        )
        return self.dal.count_pending_orders_for_branch(
            tenant_id=tenant_id,
            branch_id=branch_id,
        )

    def list_orders_for_console_tenant(
        self,
        *,
        user,
        tenant_id: UUID,
        branch_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ):
        tenant = self.dal.get_tenant_for_console(tenant_id=tenant_id)
        if tenant is None:
            raise TenantNotFoundException()

        self._assert_console_tenant_owner(user=user, tenant=tenant)

        return self.dal.list_orders_for_console_tenant(
            tenant_id=tenant_id,
            branch_id=branch_id,
            status=status,
            search=search,
        )

    def list_customers_for_console_tenant(
        self,
        *,
        user,
        tenant_id: UUID,
        branch_id: Optional[str] = None,
        search: Optional[str] = None,
    ):
        from accounts.selectors.console_customers_dal import (
            ConsoleCustomersDataAccessLayer,
        )

        tenant = self.dal.get_tenant_for_console(tenant_id=tenant_id)
        if tenant is None:
            raise TenantNotFoundException()

        self._assert_console_tenant_owner(user=user, tenant=tenant)

        resolved_branch_id = None
        if branch_id:
            try:
                branch = self.dal.get_branch_for_console(
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                )
            except (TypeError, ValueError):
                raise BranchNotFoundException()
            if branch is None:
                raise BranchNotFoundException()
            resolved_branch_id = branch.id

        return ConsoleCustomersDataAccessLayer.list_customers_for_console_tenant(
            tenant_id=tenant_id,
            branch_id=resolved_branch_id,
            search=search,
        )

    @staticmethod
    def _assert_console_tenant_owner(*, user, tenant) -> None:
        if tenant.owner.user_id != user.id:
            raise NotTenantOwnerException()

    # ------------------------------------------------------------------
    # Discount validation
    # ------------------------------------------------------------------

    def validate_discount(
        self, *, branch_id: int, discount_code: str, subtotal: Optional[Decimal] = None
    ) -> dict:
        branch = self._get_active_branch(branch_id)

        if not discount_code:
            raise InvalidDiscountCodeException("Discount code is required.")

        discount_amount = self._resolve_discount(branch.tenant, discount_code)

        return {
            "valid": True,
            "discount_code": discount_code,
            "discount_amount": discount_amount,
        }

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    def _get_active_branch(self, branch_id: int):
        branch = self.dal.get_active_branch(branch_id)
        if branch is None:
            raise BranchNotFoundException()
        return branch

    def _validate_order_type_requirements(self, order_type, validated_data):
        if order_type == OrderType.DELIVERY and not validated_data.get("delivery_address"):
            raise DeliveryAddressRequiredException()
        if order_type == OrderType.DINE_IN and not validated_data.get("table_number"):
            raise TableNumberRequiredException()

    def _validate_branch_checkout(self, branch, *, order_type: str, payment_method: str) -> None:
        if not branch.ordering_enabled:
            raise OrderingDisabledException()

        order_type_rules = {
            OrderType.DELIVERY: branch.delivery_enabled,
            OrderType.PICKUP: branch.pickup_enabled,
            OrderType.DINE_IN: branch.table_ordering_enabled,
        }
        if not order_type_rules.get(order_type, False):
            raise OrderTypeNotEnabledException(
                f"Order type '{order_type}' is not enabled for this branch."
            )

        payment_rules = {
            PaymentMethod.CASH: branch.cash_payment_enabled,
            PaymentMethod.CARD: branch.card_payment_enabled,
            PaymentMethod.ONLINE: branch.online_payment_enabled,
            PaymentMethod.WALLET: branch.wallet_payment_enabled,
        }
        if not payment_rules.get(payment_method, False):
            raise PaymentMethodNotEnabledException(
                f"Payment method '{payment_method}' is not enabled for this branch."
            )

        if (
            order_type == OrderType.DELIVERY
            and payment_method == PaymentMethod.CASH
            and not branch.cash_on_delivery_enabled
        ):
            raise CashOnDeliveryNotEnabledException()

    def _validate_minimum_order(self, branch, subtotal: Decimal) -> None:
        minimum = branch.minimum_order_amount
        if minimum is not None and subtotal < Decimal(str(minimum)):
            raise MinimumOrderNotMetException(
                f"Minimum order amount is {minimum}."
            )

    def _resolve_delivery_address_snapshot(self, customer, address_data: dict, branch):
        snapshot = self.address_domain.resolve_checkout_snapshot(
            user=customer,
            branch=branch,
            delivery_data=address_data,
        )
        return self.dal.create_delivery_address(**snapshot)

    def _load_and_validate_menu_items(self, tenant, items_data):
        ids = [item["menu_item_id"] for item in items_data]
        menu_items = self.dal.get_menu_items_by_ids(ids)
        menu_items_by_id = {mi.id: mi for mi in menu_items}

        for item_id in ids:
            menu_item = menu_items_by_id.get(item_id)
            if menu_item is None:
                raise MenuItemNotFoundException(
                    f"Menu item {item_id} not found."
                )
            if not menu_item.is_active:
                raise MenuItemNotFoundException(
                    f"Menu item {item_id} not found or inactive."
                )
            if not menu_item.available:
                raise MenuItemUnavailableException(
                    f"Menu item {item_id} is unavailable for ordering."
                )
            if menu_item.branch.tenant_id != tenant.id:
                raise MenuItemNotInTenantException(
                    f"Menu item {item_id} does not belong to this tenant."
                )

        return menu_items_by_id

    def _validate_item_extras(self, menu_item_id: int, extra_ids: list):
        if not extra_ids:
            return []

        links = self.dal.get_extra_links_for_item(menu_item_id, extra_ids)
        links_by_extra_id = {link.extra_id: link for link in links}

        missing = set(extra_ids) - set(links_by_extra_id.keys())
        if missing:
            raise ExtraNotAvailableException(
                f"Extras {sorted(missing)} are not available for this item."
            )

        return [
            (extra_id, links_by_extra_id[extra_id].price) for extra_id in extra_ids
        ]

    def _create_items_and_extras(self, order, items_data, menu_items_by_id) -> Decimal:
        subtotal = Decimal("0")
        pending_extras: list[OrderItemExtra] = []

        for item_data in items_data:
            menu_item = menu_items_by_id[item_data["menu_item_id"]]

            extras = self._validate_item_extras(
                menu_item.id, item_data.get("extras", [])
            )
            extras_total = sum((price for _, price in extras), Decimal("0"))
            item_total = (menu_item.price *
                          item_data["quantity"]) + extras_total

            order_item = self.dal.create_order_item(
                order,
                menu_item=menu_item,
                name=menu_item.name,
                image=getattr(menu_item, "image", "") or "",
                quantity=item_data["quantity"],
                unit_price=menu_item.price,
                total_price=item_total,
                notes=item_data.get("notes", ""),
            )

            for extra_id, extra_price in extras:
                pending_extras.append(
                    OrderItemExtra(
                        order_item=order_item,
                        extra_id=extra_id,
                        price=extra_price,
                    )
                )

            subtotal += item_total

        if pending_extras:
            self.dal.bulk_create_order_item_extras(pending_extras)

        return subtotal

    def _apply_totals(
        self, order, tenant, order_type, subtotal: Decimal, discount_amount: Decimal
    ) -> None:
        tax_amount = self._round(subtotal * (tenant.tax_percentage / Decimal("100")))

        service_charge = Decimal("0")
        if order_type == OrderType.DINE_IN:
            service_charge_pct = tenant.service_charge_percentage or Decimal("0")
            service_charge = self._round(
                subtotal * (service_charge_pct / Decimal("100")))

        total_amount = subtotal - discount_amount + tax_amount + service_charge

        self.dal.update_order_fields(
            order,
            subtotal=subtotal,
            discount_amount=discount_amount,
            tax=tax_amount,
            service_charge=service_charge,
            total=total_amount,
        )

    def _resolve_discount(self, tenant, discount_code: str) -> Decimal:
        if not discount_code:
            return Decimal("0")

        discount = self.dal.get_discount_by_code(tenant.id, discount_code)
        if discount is None:
            raise InvalidDiscountCodeException(
                f"Discount code '{discount_code}' is invalid or expired."
            )
        return Decimal("0")

    def _generate_order_number(self) -> str:
        prefix = f"ORD-{datetime.now():%Y%m%d}"
        for _ in range(5):
            candidate = f"{prefix}-{uuid.uuid4().hex[:6].upper()}"
            if not self.dal.order_number_exists(candidate):
                return candidate
        return f"{prefix}-{uuid.uuid4().hex.upper()}"

    @staticmethod
    def _round(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
