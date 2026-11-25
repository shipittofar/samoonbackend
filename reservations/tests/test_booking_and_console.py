from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import Notification
from orders.tests.test_console_websocket import assign_role, make_branch, make_tenant_with_owner, make_user
from reservations.models import Reservation, ReservationStatus
from reservations.services.slots import available_slots, branch_zone
from tenants.models.tenant import WorkingHour


def api(user=None):
    c = APIClient()
    if user:
        c.force_authenticate(user)
    return c


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant, name="Valiasr")  # reservations_enabled, no hours: 12:00-22:00 Tehran
        self.customer = make_user()
        self.day = timezone.now().astimezone(branch_zone(self.branch)).date() + timedelta(days=3)

    def hours(self, opens, closes, day=None, closed=False):
        WorkingHour.objects.create(
            branch=self.branch, day=(day or self.day).weekday(), open_time=opens, close_time=closes, is_closed=closed
        )

    def slots(self, **params):
        return api().get(
            "/api/reservations/available-slots/", {"branch_id": self.branch.id, "date": self.day.isoformat(), **params}
        )

    def book(self, user=None, **over):
        body = {
            "branch_id": str(self.branch.id), "date": self.day.isoformat(), "time": "19:00", "party_size": 2,
            "guest_name": "Sara", "guest_phone": "+989120000000", **over,
        }
        return api(user or self.customer).post("/api/reservations/", body, format="json")


class SlotTests(Base):
    def test_default_hours_and_step(self):
        got = self.slots().data
        self.assertEqual((got[0], got[1], got[-1]), ("12:00", "12:30", "21:00"))

    def test_working_hours_closed_day_and_after_midnight(self):
        self.hours(time(18), time(2))
        self.assertEqual(self.slots().data[0], "18:00")
        self.assertEqual(self.slots().data[-1], "23:30")
        # The rest of that evening belongs to the next calendar day...
        self.day += timedelta(days=1)
        self.assertEqual(self.slots().data, ["00:00", "00:30", "01:00"])  # ...which has no hours of its own.

    def test_lead_time_and_horizon(self):
        zone = branch_zone(self.branch)
        now = datetime.combine(self.day, time(18, 40), tzinfo=zone)
        self.assertEqual(available_slots(self.branch, self.day, now=now)[0].strftime("%H:%M"), "20:00")
        self.day = self.day - timedelta(days=10)
        self.assertEqual(self.slots().data, [])
        self.day = self.day + timedelta(days=100)
        self.assertEqual(self.slots().data, [])

    def test_branch_time_zone(self):
        self.branch.time_zone = "Europe/London"
        self.branch.save()
        first = available_slots(self.branch, self.day)[0]
        self.assertEqual(first.utcoffset(), branch_zone(self.branch).utcoffset(first.replace(tzinfo=None)))
        self.assertEqual(first.hour, 12)

    def test_capacity(self):
        self.branch.max_capacity = 10
        self.branch.save()
        self.assertEqual(self.book(party_size=8).status_code, 201)
        self.assertIn("19:00", self.slots(guests=2).data)
        self.assertNotIn("19:00", self.slots(guests=3).data)
        self.assertNotIn("20:30", self.slots(guests=3).data)  # table still held
        self.assertIn("21:00", self.slots(guests=3).data)

    def test_public_and_validated(self):
        self.assertEqual(self.slots().status_code, 200)
        bad = api()
        bad.credentials(HTTP_AUTHORIZATION="Bearer expired")
        res = bad.get("/api/reservations/available-slots/", {"branch_id": self.branch.id, "date": self.day.isoformat()})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.slots(date="nope").status_code, 400)
        self.branch.reservations_enabled = False
        self.branch.save()
        self.assertEqual(self.slots().status_code, 400)


class BookingTests(Base):
    def test_books_the_branch_local_time_and_tells_the_owner(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.book()
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.data["local_date"], res.data["local_time"]), (self.day.isoformat(), "19:00"))
        self.assertEqual((res.data["status"], len(res.data["confirmation_code"])), ("pending", 8))
        stored = Reservation.objects.get()
        self.assertEqual(stored.reserved_at, datetime.combine(self.day, time(15, 30), tzinfo=dt_timezone.utc))
        n = Notification.objects.get(recipient=self.owner, type="reservation_created")
        self.assertEqual(n.data["when"], f"{self.day.isoformat()} 19:00")

    def test_refuses_times_that_are_not_offered(self):
        for bad in ("19:10", "11:30", "21:30"):
            res = self.book(time=bad)
            self.assertEqual(res.status_code, 400, bad)
        past = (timezone.now() - timedelta(days=1)).date().isoformat()
        self.assertEqual(self.book(date=past).status_code, 400)
        self.assertEqual(self.book(time=None).status_code, 400)
        self.assertEqual(self.book(date=self.day.isoformat(), time="").status_code, 400)
        self.assertFalse(Reservation.objects.exists())

    def test_capacity_and_double_booking(self):
        self.branch.max_capacity = 5
        self.branch.save()
        self.assertEqual(self.book(party_size=6).status_code, 400)
        self.assertEqual(self.book(party_size=3).status_code, 201)
        self.assertEqual(self.book(party_size=1, time="20:00").status_code, 400)  # same guest, overlapping
        other = make_user()
        self.assertEqual(self.book(other, party_size=3).status_code, 400)  # 2 seats left
        self.assertEqual(self.book(other, party_size=2).status_code, 201)

    def test_sign_in_required(self):
        self.assertEqual(api().post("/api/reservations/", {}, format="json").status_code, 401)


class ConsoleTests(Base):
    def setUp(self):
        super().setUp()
        self.other_branch = make_branch(self.tenant, name="Other")
        self.a = self.make(self.branch, "Ali", 19)
        self.b = self.make(self.branch, "Bahar", 13, ReservationStatus.CONFIRMED)
        self.c = self.make(self.other_branch, "Cyrus", 15)
        self.url = f"/api/reservations/console-reservations/tenants/{self.tenant.id}/"

    def make(self, branch, name, hour, status=ReservationStatus.PENDING, day=None):
        return Reservation.objects.create(
            branch=branch, customer=self.customer, guest_name=name, guest_phone="0912", party_size=2, status=status,
            reserved_at=datetime.combine(day or self.day, time(hour), tzinfo=branch_zone(branch)),
        )

    def names(self, user, **params):
        return [r["guest_name"] for r in api(user).get(self.url, params).data["results"]]

    def test_owner_sees_every_branch_filtered(self):
        self.assertEqual(self.names(self.owner), ["Bahar", "Cyrus", "Ali"])
        self.assertEqual(self.names(self.owner, branch_id=self.branch.id), ["Bahar", "Ali"])
        self.assertEqual(self.names(self.owner, search="cyr"), ["Cyrus"])
        res = api(self.owner).get(self.url, {"status": "confirmed"}).data
        self.assertEqual((res["count"], res["counts"]), (1, {"pending": 2, "confirmed": 1}))

    def test_day_is_the_branch_local_day(self):
        self.make(self.branch, "Late", 1)  # 01:00 Tehran is the previous day in UTC
        self.make(self.branch, "Next", 1, day=self.day + timedelta(days=1))
        self.assertEqual(self.names(self.owner, date=self.day.isoformat()), ["Late", "Bahar", "Cyrus", "Ali"])

    def test_staff_see_only_their_branch(self):
        host = make_user()
        assign_role(host, self.tenant, "waiter", branch=self.other_branch)
        self.assertEqual(self.names(host), ["Cyrus"])
        self.assertEqual(api(host).get(self.url, {"branch_id": self.branch.id}).status_code, 403)
        self.assertEqual(api(host).get(f"{self.url}{self.a.id}/").status_code, 403)
        self.assertEqual(api(host).get(f"{self.url}{self.c.id}/").status_code, 200)

    def test_outsiders(self):
        other_owner, other_tenant = make_tenant_with_owner()
        for user in (self.customer, other_owner):
            self.assertEqual(api(user).get(self.url).status_code, 403)
            self.assertEqual(api(user).get(f"{self.url}{self.a.id}/").status_code, 403)
        self.assertEqual(api().get(self.url).status_code, 401)
        # Right owner of the wrong business: the id does not exist there.
        wrong = f"/api/reservations/console-reservations/tenants/{other_tenant.id}/{self.a.id}/"
        self.assertEqual(api(other_owner).get(wrong).status_code, 404)

    def test_detail_and_status_steps(self):
        detail = api(self.owner).get(f"{self.url}{self.a.id}/").data
        self.assertEqual((detail["guest_name"], detail["customer_id"]), ("Ali", str(self.customer.id)))
        for status in ("confirmed", "seated", "completed"):
            res = api(self.owner).patch(f"/api/reservations/{self.a.id}/status/", {"status": status}, format="json")
            self.assertEqual(res.data["status"], status)

    def test_bad_filters(self):
        for params in ({"date": "x"}, {"status": "x"}, {"branch_id": "x"}):
            self.assertEqual(api(self.owner).get(self.url, params).status_code, 400)
