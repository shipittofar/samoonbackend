from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from orders.tests.test_console_websocket import make_branch, make_tenant_with_owner, make_user
from reservations.models import Reservation, ReservationStatus

URL = "/api/reservations/"


class CustomerReservationsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant, name="Valiasr")
        self.customer = make_user()
        self.client = APIClient()
        self.client.force_authenticate(self.customer)

    def make(self, customer=None, *, hours=24, status=ReservationStatus.PENDING, branch=None):
        return Reservation.objects.create(
            branch=branch or self.branch, customer=customer or self.customer, guest_name="Sara", guest_phone="0912",
            party_size=3, reserved_at=timezone.now() + timedelta(hours=hours), status=status,
        )

    def test_own_reservations_at_every_business_latest_first(self):
        _, other_tenant = make_tenant_with_owner()
        early = self.make(hours=5)
        late = self.make(hours=50, branch=make_branch(other_tenant, name="Other"))
        self.make(customer=make_user())
        data = self.client.get(URL).data
        self.assertEqual([r["id"] for r in data["results"]], [str(late.id), str(early.id)])
        self.assertEqual(data["count"], 2)
        row = data["results"][1]
        self.assertEqual((row["branch_name"], row["business_name"], row["party_size"]), ("Valiasr", self.tenant.name, 3))

    def test_can_cancel_only_open_future_ones(self):
        rows = {
            self.make().id: True,
            self.make(status=ReservationStatus.CONFIRMED).id: True,
            self.make(status=ReservationStatus.SEATED).id: False,
            self.make(status=ReservationStatus.CANCELLED).id: False,
            self.make(hours=-2).id: False,
        }
        got = {r["id"]: r["can_cancel"] for r in self.client.get(URL).data["results"]}
        self.assertEqual(got, {str(k): v for k, v in rows.items()})

    def test_pages_and_query_count(self):
        for i in range(25):
            self.make(hours=i + 1)
        with self.assertNumQueries(2):  # count + one joined page
            first = self.client.get(URL).data
        self.assertEqual((first["count"], len(first["results"])), (25, 20))
        self.assertEqual(len(self.client.get(URL, {"page": 2}).data["results"]), 5)

    def test_sign_in_required_and_not_a_business_list(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)
        self.assertEqual(self.client.get(URL, {"admin": "true"}).status_code, 405)

    def test_notification_text_uses_business_local_time(self):
        from datetime import datetime, timezone as dt_timezone

        from notifications.events import _when

        self.assertEqual(_when(datetime(2026, 11, 26, 13, 30, tzinfo=dt_timezone.utc)), "2026-11-26 17:00")

    def test_cancel_own_only(self):
        mine, theirs = self.make(), self.make(customer=make_user())
        res = self.client.post(f"{URL}{mine.id}/cancel/")
        self.assertEqual((res.data["status"], res.data["can_cancel"]), ("cancelled", False))
        self.assertEqual(self.client.post(f"{URL}{theirs.id}/cancel/").status_code, 404)
