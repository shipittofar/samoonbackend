# orders/selectors.py
from typing import Iterable, List, Optional
from uuid import UUID
from tenants.models import Branch, Tenant
from tenants.selectors.tenant_availability import OPERATIONAL_TENANT_LOOKUP
from django.db.models import Q, QuerySet

from orders.models import Order, OrderDeliveryAddress, OrderItem, OrderItemExtra, OrderStatusHistory


class OrdersDataAccessLayer:
    """
    All direct ORM access for orders is centralized here.
    Only the business logic layer should talk to the database through this class.
    """

    @staticmethod
    def create_order(**fields) -> Order:
        return Order.objects.create(**fields)

    @staticmethod
    def create_delivery_address(**fields) -> OrderDeliveryAddress:
        return OrderDeliveryAddress.objects.create(**fields)

    @staticmethod
    def create_order_item(order: Order, **fields) -> OrderItem:
        return OrderItem.objects.create(order=order, **fields)

    @staticmethod
    def bulk_create_order_item_extras(
        extras: Iterable[OrderItemExtra],
    ) -> List[OrderItemExtra]:
        return OrderItemExtra.objects.bulk_create(extras)

    @staticmethod
    def create_status_history(order: Order, status: str, note: str = "") -> OrderStatusHistory:
        return OrderStatusHistory.objects.create(order=order, status=status, note=note)

    @staticmethod
    def delete_order_items(order: Order) -> None:
        # Cascades to OrderItemExtra via on_delete=CASCADE.
        order.items.all().delete()

    @staticmethod
    def update_order_fields(order: Order, **fields) -> Order:
        for field_name, value in fields.items():
            setattr(order, field_name, value)
        order.save(update_fields=list(fields.keys()))
        return order

    @staticmethod
    def get_order_with_relations(queryset: "QuerySet[Order]") -> "QuerySet[Order]":
        return queryset.select_related(
            "branch", "branch__tenant", "customer", "delivery_address"
        ).prefetch_related("items__menu_item", "items__extras__extra")

    @classmethod
    def get_order_by_id(cls, order_id) -> Optional[Order]:
        return cls.get_order_with_relations(Order.objects).filter(pk=order_id).first()

    @classmethod
    def get_order_by_public_id_for_customer(
        cls, public_id: UUID, customer_id: int
    ) -> Optional[Order]:
        # Order.id is itself the UUID public identifier now.
        return (
            cls.get_order_with_relations(Order.objects)
            .filter(pk=public_id, customer_id=customer_id)
            .first()
        )

    def get_branch_for_console(self, *, tenant_id: UUID, branch_id: UUID,):
        return (
            Branch.objects
            .select_related("tenant", "tenant__owner", "tenant__owner__user")
            .filter(
                tenant_id=tenant_id,
                id=branch_id,
            )
            .first()
        )

    def get_tenant_for_console(self, *, tenant_id: UUID) -> Optional[Tenant]:
        return (
            Tenant.objects
            .select_related("owner", "owner__user")
            .filter(id=tenant_id)
            .first()
        )

    def list_orders_for_console(
        self,
        *,
        tenant_id: UUID,
        branch_id: UUID,
    ):
        return self.list_orders_for_console_tenant(
            tenant_id=tenant_id,
            branch_id=branch_id,
        )

    def count_pending_orders_for_branch(
        self,
        *,
        tenant_id: UUID,
        branch_id: UUID,
    ) -> int:
        from orders.constants import PENDING_ORDER_STATUSES

        return Order.objects.filter(
            branch_id=branch_id,
            branch__tenant_id=tenant_id,
            status__in=PENDING_ORDER_STATUSES,
        ).count()

    def list_orders_for_console_tenant(
        self,
        *,
        tenant_id: UUID,
        branch_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ):
        queryset = Order.objects.filter(branch__tenant_id=tenant_id)

        if branch_id is not None:
            queryset = queryset.filter(branch_id=branch_id)

        if status:
            queryset = queryset.filter(status=status)

        if search:
            queryset = queryset.filter(
                Q(order_number__icontains=search)
                | Q(customer__email__icontains=search)
                | Q(customer__phone_number__icontains=search)
            )

        return (
            queryset
            .select_related(
                "customer",
                "branch",
                "branch__tenant",
            )
            .prefetch_related(
                "items",
                "items__menu_item",
            )
            .order_by("-created_at")
        )

    @classmethod
    def get_order_by_public_id_for_update(cls, public_id: UUID) -> Optional[Order]:
        return (
            Order.objects
            .select_related(
                "branch",
                "branch__tenant",
                "branch__tenant__owner",
                "branch__tenant__owner__user",
                "customer",
            )
            .select_for_update(of=("self",))
            .filter(pk=public_id)
            .first()
        )

    @classmethod
    def get_orders_for_customer(cls, customer_id: int) -> "QuerySet[Order]":
        return cls.get_order_with_relations(Order.objects).filter(
            customer_id=customer_id
        )

    @staticmethod
    def order_number_exists(order_number: str) -> bool:
        return Order.objects.filter(order_number=order_number).exists()

    @staticmethod
    def get_menu_items_by_ids(menu_item_ids: Iterable[int]):
        from menu.models import MenuItem
        return MenuItem.objects.filter(id__in=menu_item_ids).select_related(
            "branch", "branch__tenant"
        )

    @staticmethod
    def get_extra_links_for_item(menu_item_id: int, extra_ids: Iterable[int]):
        from menu.models import MenuItemExtra
        return MenuItemExtra.objects.filter(
            item_id=menu_item_id,
            extra_id__in=extra_ids,
            extra__available=True,
        ).select_related("extra")

    @staticmethod
    def get_active_branch(branch_id: int):
        from tenants.models import Branch
        return (
            Branch.objects.select_related("tenant")
            .filter(pk=branch_id, is_active=True, **OPERATIONAL_TENANT_LOOKUP)
            .first()
        )

    @staticmethod
    def get_discount_by_code(tenant_id: int, discount_code: str):
        # Placeholder until a real Discount/Coupon model exists.
        return None

