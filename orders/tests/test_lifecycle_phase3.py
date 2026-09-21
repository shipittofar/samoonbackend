"""Phase 3 order/reservation cancel-only lifecycle."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from menu.models import MenuCategory, MenuItem
from orders.admin.orders import OrderAdmin
from orders.models import (
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    OrderType,
    PaymentMethod,
)
from orders.services.orders_bll import OrdersBusinessLogicLayer
from reservations.models import Reservation, ReservationStatus
from reservations.services.reservations_bll import ReservationsBusinessLogicLayer
from tenants.models import Branch, Owner, Tenant


def make_user():
    user = User(
        id=uuid.uuid4(),
        phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
        email=f"{uuid.uuid4().hex}@example.com",
        first_name="Test",
        last_name="User",
    )
    user.set_password("testpass123")
    user.save()
    return user


class OrderReservationLifecycleTests(TestCase):
    def setUp(self):
        owner = Owner.objects.create(user=make_user())
        tenant = Tenant.objects.create(owner=owner, name=f"T{uuid.uuid4().hex[:6]}")
        self.branch = Branch.objects.create(tenant=tenant, name="Main", pickup_enabled=True)
        self.customer = make_user()
        category = MenuCategory.objects.create(branch=self.branch, name="Mains")
        self.item = MenuItem.objects.create(
            branch=self.branch, category=category, name="Soup", price=Decimal("5.00")
        )
        self.order = Order.objects.create(
            order_number=f"ORD-{uuid.uuid4().hex[:10]}",
            customer=self.customer,
            branch=self.branch,
            order_type=OrderType.PICKUP,
            payment_method=PaymentMethod.CASH,
            status=OrderStatus.PENDING,
        )
        OrderItem.objects.create(
            order=self.order,
            menu_item=self.item,
            name="Soup",
            quantity=1,
            unit_price=Decimal("5.00"),
            total_price=Decimal("5.00"),
        )
        OrderStatusHistory.objects.create(order=self.order, status=OrderStatus.PENDING)

    def test_cancel_preserves_history_and_is_idempotent(self):
        bll = OrdersBusinessLogicLayer()
        bll.cancel_order(customer=self.customer, public_id=self.order.id)
        bll.cancel_order(customer=self.customer, public_id=self.order.id)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED)
        self.assertTrue(Order.objects.filter(id=self.order.id).exists())
        self.assertTrue(OrderItem.objects.filter(order=self.order).exists())
        self.assertTrue(OrderStatusHistory.objects.filter(order=self.order).exists())

    def test_admin_has_no_hard_delete(self):
        request = type("R", (), {"user": self.customer})()
        self.assertFalse(OrderAdmin(Order, None).has_delete_permission(request, self.order))

    def test_reservation_cancel_preserves_row(self):
        reservation = Reservation.objects.create(
            branch=self.branch,
            customer=self.customer,
            guest_name="Guest",
            guest_phone="+15550001111",
            party_size=2,
            reserved_at=timezone.now() + timedelta(hours=2),
            status=ReservationStatus.PENDING,
        )
        bll = ReservationsBusinessLogicLayer()
        bll.cancel_reservation(customer=self.customer, reservation_id=reservation.id)
        bll.cancel_reservation(customer=self.customer, reservation_id=reservation.id)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, ReservationStatus.CANCELLED)
        self.assertTrue(Reservation.objects.filter(id=reservation.id).exists())
