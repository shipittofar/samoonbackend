from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from notifications import catalog
from notifications.models import Notification, NotificationPreference
from orders.models import OrderStatus, OrderType, PaymentMethod
from orders.services.orders_bll import OrdersBusinessLogicLayer
from orders.tests.test_console_websocket import (
    access_token,
    assign_role,
    make_branch,
    make_menu_item,
    make_order,
    make_reservation,
    make_tenant_with_owner,
    make_user,
)
from reservations.models import ReservationStatus
from reservations.services.reservations_bll import ReservationsBusinessLogicLayer


def types_for(user):
    return sorted(Notification.objects.filter(recipient=user).values_list("type", flat=True))


class EventTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant, name="Valiasr")
        self.item = make_menu_item(self.branch)
        self.customer = make_user(first_name="Sara", last_name="Customer")
        self.cashier = make_user()
        assign_role(self.cashier, self.tenant, "cashier", all_locations=True)
        self.waiter_other_branch = make_user()
        other = make_branch(self.tenant, name="Other")
        assign_role(self.waiter_other_branch, self.tenant, "waiter", branch=other)

    def test_new_order_tells_owner_and_staff_who_handle_orders(self):
        with self.captureOnCommitCallbacks(execute=True):
            OrdersBusinessLogicLayer().create_order(
                customer=self.customer,
                validated_data={
                    "branch_id": self.branch.id,
                    "order_type": OrderType.PICKUP,
                    "payment_method": PaymentMethod.CASH,
                    "items": [{"menu_item_id": self.item.id, "quantity": 1}],
                },
            )
        self.assertEqual(types_for(self.owner), ["order_created"])
        self.assertEqual(types_for(self.cashier), ["order_created"])
        self.assertEqual(types_for(self.waiter_other_branch), [])  # not their branch
        self.assertEqual(types_for(self.customer), [])  # they did it themselves
        n = Notification.objects.get(recipient=self.owner)
        self.assertEqual(n.tenant_id, self.tenant.id)
        self.assertEqual(n.link_href, f"/console/orders/{n.data['order_id']}")

    def test_status_change_tells_the_customer(self):
        order = make_order(self.branch, customer=self.customer, status=OrderStatus.PENDING)
        with self.captureOnCommitCallbacks(execute=True):
            OrdersBusinessLogicLayer().update_order_status(
                user=self.owner, public_id=order.id, new_status=OrderStatus.CONFIRMED
            )
        n = Notification.objects.get(recipient=self.customer)
        self.assertEqual(n.type, "order_status_changed")
        self.assertIsNone(n.tenant_id)  # personal, shows in the customer's own bell
        _, message = catalog.render(n.type, n.data, "fa")
        self.assertIn("تأیید شد", message)
        self.assertEqual(types_for(self.owner), [])

    def test_customer_cancellation_tells_staff(self):
        order = make_order(self.branch, customer=self.customer, status=OrderStatus.PENDING)
        with self.captureOnCommitCallbacks(execute=True):
            OrdersBusinessLogicLayer().cancel_order(customer=self.customer, public_id=order.id)
        self.assertEqual(types_for(self.owner), ["order_cancelled_by_customer"])
        self.assertEqual(types_for(self.customer), [])

    def test_reservations(self):
        bll = ReservationsBusinessLogicLayer()
        with self.captureOnCommitCallbacks(execute=True):
            r = bll.create_reservation(
                customer=self.customer,
                validated_data={
                    "branch_id": self.branch.id, "guest_name": "Sara", "guest_phone": "+989120000000",
                    "party_size": 4, "reserved_at": make_reservation(self.branch).reserved_at,
                },
            )
        self.assertIn("reservation_created", types_for(self.owner))
        with self.captureOnCommitCallbacks(execute=True):
            bll.update_reservation_status(user=self.owner, reservation_id=r.id, new_status=ReservationStatus.CONFIRMED)
        self.assertEqual(types_for(self.customer), ["reservation_confirmed"])

    def test_a_failing_notification_never_breaks_the_order(self):
        from unittest import mock

        with mock.patch("notifications.services.Notification.objects.create", side_effect=RuntimeError("db down")):
            with self.captureOnCommitCallbacks(execute=True):
                order = OrdersBusinessLogicLayer().create_order(
                    customer=self.customer,
                    validated_data={
                        "branch_id": self.branch.id,
                        "order_type": OrderType.PICKUP,
                        "payment_method": PaymentMethod.CASH,
                        "items": [{"menu_item_id": self.item.id, "quantity": 1}],
                    },
                )
        self.assertIsNotNone(order.id)

    def test_preference_turns_a_category_off(self):
        NotificationPreference.objects.create(user=self.owner, tenant=self.tenant, category="order", enabled=False)
        with self.captureOnCommitCallbacks(execute=True):
            OrdersBusinessLogicLayer().create_order(
                customer=self.customer,
                validated_data={
                    "branch_id": self.branch.id,
                    "order_type": OrderType.PICKUP,
                    "payment_method": PaymentMethod.CASH,
                    "items": [{"menu_item_id": self.item.id, "quantity": 1}],
                },
            )
        self.assertEqual(types_for(self.owner), [])
        self.assertEqual(types_for(self.cashier), ["order_created"])

    def test_business_request_flow(self):
        from tenants.services import business_request_bll

        root = make_user(is_superuser=True, is_staff=True)
        applicant = make_user()
        with self.captureOnCommitCallbacks(execute=True):
            item = business_request_bll.file_request(user=applicant, name="Cafe Nima", business_type="cafe", city="Tehran")
        self.assertEqual(types_for(root), ["business_request_created"])
        with self.captureOnCommitCallbacks(execute=True):
            business_request_bll.reject(request_id=item.id, actor=root, reason="Missing address")
        n = Notification.objects.get(recipient=applicant)
        self.assertEqual(n.type, "business_request_rejected")
        self.assertIn("Missing address", catalog.render(n.type, n.data, "en")[1])

    def test_password_change_alert(self):
        from accounts.services.auth_service import PasswordAuthBusinessLogicLayer

        user = make_user()
        with self.captureOnCommitCallbacks(execute=True):
            PasswordAuthBusinessLogicLayer.change_password(user, "testpass123", "BrandNewPass456!")
        self.assertEqual(types_for(user), ["password_changed"])


class ApiTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.other = make_user()
        _, self.tenant = make_tenant_with_owner()
        self.mine = Notification.objects.create(
            recipient=self.user, tenant=self.tenant, type="order_created", category="order", priority="high",
            data={"order_number": "A1", "customer": "Sara", "branch": "Valiasr"},
        )
        self.personal = Notification.objects.create(
            recipient=self.user, type="password_changed", category="system", priority="urgent", data={},
        )
        self.theirs = Notification.objects.create(
            recipient=self.other, type="password_changed", category="system", priority="urgent", data={},
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_list_is_own_only_and_in_the_requested_language(self):
        res = self.client.get("/api/notifications/rich/", HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["unreadCount"], 2)
        titles = {n["title"] for n in body["results"]}
        self.assertIn("New order", titles)
        fa = self.client.get("/api/notifications/rich/", HTTP_ACCEPT_LANGUAGE="fa").json()
        self.assertIn("سفارش جدید", {n["title"] for n in fa["results"]})

    def test_tenant_filter_and_summary(self):
        body = self.client.get("/api/notifications/rich/", {"tenantId": str(self.tenant.id)}).json()
        self.assertEqual([n["id"] for n in body["results"]], [str(self.mine.id)])
        summary = self.client.get("/api/notifications/summary/").json()
        self.assertEqual(summary["unreadCount"], 2)
        self.assertEqual(summary["urgentCount"], 1)

    def test_read_archive_delete_and_counts(self):
        self.assertEqual(self.client.post(f"/api/notifications/{self.mine.id}/read/").json()["status"], "read")
        self.assertEqual(self.client.get("/api/notifications/unread-count/").json()["count"], 1)
        self.assertEqual(self.client.post("/api/notifications/read-all/", {}, format="json").json()["count"], 1)
        self.assertEqual(self.client.post(f"/api/notifications/{self.mine.id}/archive/").json()["status"], "archived")
        self.assertEqual(self.client.delete(f"/api/notifications/{self.personal.id}/").status_code, 204)
        self.assertEqual(self.client.get("/api/notifications/rich/").json()["count"], 1)
        stats = self.client.get("/api/notifications/statistics/").json()
        self.assertEqual(stats["archivedCount"], 1)

    def test_cannot_touch_someone_elses(self):
        self.assertEqual(self.client.get(f"/api/notifications/{self.theirs.id}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/notifications/{self.theirs.id}/read/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/notifications/{self.theirs.id}/").status_code, 404)

    def test_clients_cannot_create_notifications(self):
        res = self.client.post("/api/notifications/", {"auditAction": "x"}, format="json")
        self.assertEqual(res.status_code, 405)

    def test_anonymous_is_rejected(self):
        self.assertEqual(APIClient().get("/api/notifications/rich/").status_code, 401)

    def test_preferences(self):
        prefs = self.client.get("/api/notifications/preferences/").json()
        self.assertEqual(len(prefs), len(catalog.CATEGORIES))
        res = self.client.patch(
            "/api/notifications/preferences/order/", {"enabled": False, "minPriority": "high"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["enabled"])
        # Someone else's business is refused.
        res = self.client.patch(
            "/api/notifications/preferences/order/", {"tenantId": str(self.tenant.id), "enabled": False}, format="json"
        )
        self.assertEqual(res.status_code, 403)
        reset = self.client.post("/api/notifications/preferences/reset/", {}, format="json").json()
        self.assertTrue(all(p["enabled"] for p in reset))


class SocketTests(TransactionTestCase):
    def test_new_notification_is_pushed_to_that_user_only(self):
        from SmartRestaurant.asgi import application
        from notifications.services import _create

        alice, bob = make_user(), make_user()
        alice_token, bob_token = access_token(alice), access_token(bob)

        async def scenario():
            a = WebsocketCommunicator(application, f"/ws/notifications/?token={alice_token}&lang=en")
            b = WebsocketCommunicator(application, f"/ws/notifications/?token={bob_token}&lang=en")
            self.assertTrue((await a.connect())[0])
            self.assertTrue((await b.connect())[0])
            self.assertEqual((await a.receive_json_from())["type"], "connection_established")
            await b.receive_json_from()
            from channels.db import database_sync_to_async

            await database_sync_to_async(_create)(recipients=[alice], type_="password_changed", data={})
            event = await a.receive_json_from(timeout=5)
            self.assertEqual(event["type"], "notification.new")
            self.assertEqual(event["data"]["title"], "Password changed")
            self.assertEqual(event["unreadCount"], 1)
            self.assertTrue(await b.receive_nothing(timeout=0.5))
            await a.disconnect()
            await b.disconnect()

        async_to_sync(scenario)()

    def test_anonymous_socket_is_refused(self):
        from SmartRestaurant.asgi import application

        async def scenario():
            c = WebsocketCommunicator(application, "/ws/notifications/")
            connected, code = await c.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4001)

        async_to_sync(scenario)()
