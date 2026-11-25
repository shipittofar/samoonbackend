"""Channels tests for the Console workspace websocket."""
import uuid
from datetime import time, timedelta
from decimal import Decimal

from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from django.db import transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from access.models import StaffMembership, StaffMembershipStatus
from access.tests.helpers import create_canonical_assignment, get_role
from accounts.models import User
from menu.models import MenuCategory, MenuItem
from orders.models import Order, OrderStatus, OrderType, PaymentMethod
from orders.services.orders_bll import OrdersBusinessLogicLayer
from reservations.models import Reservation, ReservationStatus
from reservations.services.reservations_bll import ReservationsBusinessLogicLayer
from tenants.models import Branch, Owner, Tenant, TenantStatus


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


def access_token(user) -> str:
    return str(RefreshToken.for_user(user).access_token)


def make_tenant_with_owner():
    user = make_user()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
        status=TenantStatus.ACTIVE,
        is_active=True,
        tax_percentage=Decimal("0"),
    )
    return user, tenant


def make_branch(tenant, **kwargs):
    defaults = {
        "name": f"Branch {uuid.uuid4().hex[:6]}",
        "pickup_enabled": True,
        "reservations_enabled": True,
        "is_active": True,
    }
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


def make_menu_item(branch):
    category = MenuCategory.objects.create(branch=branch, name="Mains")
    return MenuItem.objects.create(
        branch=branch, category=category, name="Burger", price=Decimal("10.00")
    )


def make_order(branch, **kwargs):
    defaults = {
        "order_number": f"ORD-{uuid.uuid4().hex[:10]}",
        "branch": branch,
        "order_type": OrderType.PICKUP,
        "payment_method": PaymentMethod.CASH,
        "status": OrderStatus.PENDING,
        "total": Decimal("10.00"),
    }
    defaults.update(kwargs)
    return Order.objects.create(**defaults)


def make_reservation(branch, **kwargs):
    defaults = {
        "branch": branch,
        "guest_name": "Guest",
        "guest_phone": "+15550001111",
        "party_size": 2,
        "reserved_at": timezone.now() + timedelta(hours=2),
        "status": ReservationStatus.PENDING,
    }
    defaults.update(kwargs)
    return Reservation.objects.create(**defaults)


def assign_role(user, tenant, role_slug, *, branch=None, all_locations=False):
    membership = StaffMembership.objects.create(
        user=user,
        tenant=tenant,
        status=StaffMembershipStatus.ACTIVE,
    )
    create_canonical_assignment(
        membership=membership,
        role=get_role(role_slug),
        branch=branch,
        all_locations=all_locations,
    )
    return membership


def communicator_for(user, branch_id):
    from SmartRestaurant.asgi import application

    token = access_token(user)
    return WebsocketCommunicator(
        application,
        f"/ws/console/{branch_id}/?token={token}",
    )


class ConsoleWebsocketTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.owner_a, self.tenant_a = make_tenant_with_owner()
        self.branch_a = make_branch(self.tenant_a, name="A")
        self.branch_b = make_branch(self.tenant_a, name="B")
        self.owner_b, self.tenant_b = make_tenant_with_owner()
        self.branch_tenant_b = make_branch(self.tenant_b, name="TB")
        self.item_a = make_menu_item(self.branch_a)
        self.customer = make_user()
        self.orders_bll = OrdersBusinessLogicLayer()
        self.reservations_bll = ReservationsBusinessLogicLayer()

    def _run(self, scenario):
        async_to_sync(scenario)()

    async def _open(self, user, branch):
        communicator = await sync_to_async(communicator_for)(user, branch.id)
        connected, close_code = await communicator.connect()
        return communicator, connected, close_code

    def test_authenticated_owner_connects(self):
        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            hello = await communicator.receive_json_from()
            self.assertEqual(hello["type"], "connection_established")
            self.assertEqual(hello["data"]["tenant_id"], str(self.tenant_a.id))
            self.assertEqual(hello["data"]["branch_id"], str(self.branch_a.id))
            await communicator.disconnect()

        self._run(scenario)


    def test_missing_token_is_rejected(self):
        from SmartRestaurant.asgi import application

        async def scenario():
            communicator = WebsocketCommunicator(
                application,
                f"/ws/console/{self.branch_a.id}/",
            )
            connected, code = await communicator.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4001)

        self._run(scenario)

    def test_unauthorized_branch_is_rejected(self):
        async def scenario():
            communicator, connected, close_code = await self._open(
                self.owner_a, self.branch_tenant_b
            )
            self.assertFalse(connected)
            self.assertEqual(close_code, 4003)
            await communicator.disconnect()

        self._run(scenario)

    def test_staff_cannot_connect_to_other_branch(self):
        waiter = make_user()
        assign_role(waiter, self.tenant_a, "waiter", branch=self.branch_a)

        async def scenario():
            communicator, connected, close_code = await self._open(waiter, self.branch_b)
            self.assertFalse(connected)
            self.assertEqual(close_code, 4003)
            await communicator.disconnect()

        self._run(scenario)

    def test_staff_can_connect_to_assigned_branch(self):
        waiter = make_user()
        assign_role(waiter, self.tenant_a, "waiter", branch=self.branch_a)

        async def scenario():
            communicator, connected, _ = await self._open(waiter, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await communicator.disconnect()

        self._run(scenario)

    def test_query_injection_does_not_change_group(self):
        from SmartRestaurant.asgi import application

        async def scenario():
            token = await sync_to_async(access_token)(self.owner_a)
            communicator = WebsocketCommunicator(
                application,
                (
                    f"/ws/console/{self.branch_a.id}/"
                    f"?token={token}&tenant_id={self.tenant_b.id}"
                    f"&branch_id={self.branch_tenant_b.id}"
                ),
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            hello = await communicator.receive_json_from()
            self.assertEqual(hello["data"]["branch_id"], str(self.branch_a.id))
            self.assertEqual(hello["data"]["tenant_id"], str(self.tenant_a.id))
            await communicator.disconnect()

        self._run(scenario)

    def test_client_cannot_join_another_group_via_message(self):
        async def scenario():
            communicator_a, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator_a.receive_json_from()
            await communicator_a.send_json_to(
                {
                    "action": "join",
                    "group": f"console.{self.tenant_b.id}.{self.branch_tenant_b.id}",
                    "tenant_id": str(self.tenant_b.id),
                    "branch_id": str(self.branch_tenant_b.id),
                }
            )
            other_order = await sync_to_async(make_order)(self.branch_tenant_b)
            await sync_to_async(self.orders_bll.update_order_status)(
                user=self.owner_b,
                public_id=other_order.id,
                new_status=OrderStatus.CONFIRMED,
            )
            self.assertTrue(await communicator_a.receive_nothing())
            await communicator_a.disconnect()

        self._run(scenario)

    def test_order_create_emits_order_changed(self):
        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            order = await sync_to_async(self.orders_bll.create_order)(
                customer=self.customer,
                validated_data={
                    "branch_id": self.branch_a.id,
                    "order_type": OrderType.PICKUP,
                    "payment_method": PaymentMethod.CASH,
                    "items": [{"menu_item_id": self.item_a.id, "quantity": 1}],
                },
            )
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "order.changed")
            self.assertEqual(event["data"]["order_id"], str(order.id))
            self.assertEqual(event["data"]["tenant_id"], str(self.tenant_a.id))
            self.assertEqual(event["data"]["branch_id"], str(self.branch_a.id))
            self.assertEqual(event["data"]["status"], OrderStatus.PENDING)
            await communicator.disconnect()

        self._run(scenario)

    def test_order_pending_to_confirmed_emits_event(self):
        order = make_order(self.branch_a, status=OrderStatus.PENDING)

        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await sync_to_async(self.orders_bll.update_order_status)(
                user=self.owner_a,
                public_id=order.id,
                new_status=OrderStatus.CONFIRMED,
            )
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "order.changed")
            self.assertEqual(event["data"]["status"], OrderStatus.CONFIRMED)
            self.assertEqual(event["data"]["order_id"], str(order.id))
            await communicator.disconnect()

        self._run(scenario)

    def test_order_pending_to_cancelled_emits_event(self):
        order = make_order(
            self.branch_a, customer=self.customer, status=OrderStatus.PENDING
        )

        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await sync_to_async(self.orders_bll.cancel_order)(
                customer=self.customer, public_id=order.id
            )
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "order.changed")
            self.assertEqual(event["data"]["status"], OrderStatus.CANCELLED)
            await communicator.disconnect()

        self._run(scenario)

    def test_reservation_create_emits_reservation_changed(self):
        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            reservation = await sync_to_async(self.reservations_bll.create_reservation)(
                customer=self.customer,
                validated_data={
                    "branch_id": self.branch_a.id,
                    "guest_name": "Ada",
                    "guest_phone": "+15551212",
                    "party_size": 2,
                    "date": timezone.localdate() + timedelta(days=2),
                    "time": time(13, 0),  # inside the default opening hours
                },
            )
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "reservation.changed")
            self.assertEqual(event["data"]["reservation_id"], str(reservation.id))
            self.assertEqual(event["data"]["status"], ReservationStatus.PENDING)
            self.assertEqual(event["data"]["tenant_id"], str(self.tenant_a.id))
            self.assertEqual(event["data"]["branch_id"], str(self.branch_a.id))
            await communicator.disconnect()

        self._run(scenario)

    def test_reservation_pending_to_confirmed(self):
        reservation = make_reservation(self.branch_a)

        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await sync_to_async(self.reservations_bll.update_reservation_status)(
                user=self.owner_a,
                reservation_id=reservation.id,
                new_status=ReservationStatus.CONFIRMED,
            )
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "reservation.changed")
            self.assertEqual(event["data"]["status"], ReservationStatus.CONFIRMED)
            await communicator.disconnect()

        self._run(scenario)

    def test_reservation_pending_to_cancelled(self):
        reservation = make_reservation(self.branch_a, customer=self.customer)

        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await sync_to_async(self.reservations_bll.cancel_reservation)(
                customer=self.customer, reservation_id=reservation.id
            )
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "reservation.changed")
            self.assertEqual(event["data"]["status"], ReservationStatus.CANCELLED)
            await communicator.disconnect()

        self._run(scenario)

    def test_branch_isolation_no_cross_events(self):
        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            other = await sync_to_async(make_order)(self.branch_b)
            await sync_to_async(self.orders_bll.update_order_status)(
                user=self.owner_a,
                public_id=other.id,
                new_status=OrderStatus.CONFIRMED,
            )
            self.assertTrue(await communicator.receive_nothing())
            await communicator.disconnect()

        self._run(scenario)

    def test_tenant_isolation_no_cross_events(self):
        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            foreign = await sync_to_async(make_order)(self.branch_tenant_b)
            await sync_to_async(self.orders_bll.update_order_status)(
                user=self.owner_b,
                public_id=foreign.id,
                new_status=OrderStatus.CONFIRMED,
            )
            self.assertTrue(await communicator.receive_nothing())
            await communicator.disconnect()

        self._run(scenario)

    def test_failed_order_transaction_emits_nothing(self):
        order = make_order(self.branch_a, status=OrderStatus.PENDING)

        def mutate_and_rollback():
            try:
                with transaction.atomic():
                    self.orders_bll.update_order_status(
                        user=self.owner_a,
                        public_id=order.id,
                        new_status=OrderStatus.CONFIRMED,
                    )
                    raise RuntimeError("force rollback")
            except RuntimeError:
                pass

        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await sync_to_async(mutate_and_rollback)()
            await sync_to_async(order.refresh_from_db)()
            self.assertEqual(order.status, OrderStatus.PENDING)
            self.assertTrue(await communicator.receive_nothing())
            await communicator.disconnect()

        self._run(scenario)

    def test_failed_reservation_transaction_emits_nothing(self):
        reservation = make_reservation(self.branch_a)

        def mutate_and_rollback():
            try:
                with transaction.atomic():
                    self.reservations_bll.update_reservation_status(
                        user=self.owner_a,
                        reservation_id=reservation.id,
                        new_status=ReservationStatus.CONFIRMED,
                    )
                    raise RuntimeError("force rollback")
            except RuntimeError:
                pass

        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await sync_to_async(mutate_and_rollback)()
            await sync_to_async(reservation.refresh_from_db)()
            self.assertEqual(reservation.status, ReservationStatus.PENDING)
            self.assertTrue(await communicator.receive_nothing())
            await communicator.disconnect()

        self._run(scenario)

    def test_reconnect_receives_future_events(self):
        async def scenario():
            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            await communicator.disconnect()

            communicator, connected, _ = await self._open(self.owner_a, self.branch_a)
            self.assertTrue(connected)
            await communicator.receive_json_from()
            order = await sync_to_async(make_order)(self.branch_a)
            await sync_to_async(self.orders_bll.update_order_status)(
                user=self.owner_a,
                public_id=order.id,
                new_status=OrderStatus.CONFIRMED,
            )
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "order.changed")
            await communicator.disconnect()

        self._run(scenario)

    def test_existing_order_status_websocket_still_works(self):
        from SmartRestaurant.asgi import application

        order = make_order(self.branch_a, customer=self.customer)

        async def scenario():
            token = await sync_to_async(access_token)(self.customer)
            communicator = WebsocketCommunicator(
                application,
                f"/ws/orders/{order.id}/?token={token}",
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            hello = await communicator.receive_json_from()
            self.assertEqual(hello["type"], "connection_established")
            self.assertEqual(hello["status"], OrderStatus.PENDING)
            await sync_to_async(self.orders_bll.update_order_status)(
                user=self.owner_a,
                public_id=order.id,
                new_status=OrderStatus.CONFIRMED,
            )
            event = await communicator.receive_json_from()
            self.assertEqual(event["id"], str(order.id))
            self.assertEqual(event["status"], OrderStatus.CONFIRMED)
            await communicator.disconnect()

        self._run(scenario)
