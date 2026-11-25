from datetime import datetime, time, timedelta

from notifications.models import Notification
from orders.tests.test_console_websocket import assign_role, make_tenant_with_owner, make_user
from platform_settings.models import PlatformSettingChange
from reservations.models import Reservation, ReservationStatus
from reservations.services import rules
from reservations.services.slots import branch_zone
from reservations.tests.test_booking_and_console import Base, api

PLATFORM = "/api/reservations/platform-rules/"


class RulesTests(Base):
    def setUp(self):
        super().setUp()
        self.root = make_user(is_superuser=True, is_staff=True)
        self.url = f"/api/reservations/console-reservations/tenants/{self.tenant.id}/branches/{self.branch.id}/rules/"

    def put(self, user=None, **body):
        return api(user or self.owner).put(self.url, body, format="json")

    def test_hourly_and_two_hour_businesses(self):
        self.put(slot_minutes=60, duration_minutes=60)
        self.assertEqual(self.slots().data, [f"{h}:00" for h in range(12, 22)])
        self.put(slot_minutes=120, duration_minutes=120, last_before_close_minutes=120)
        self.assertEqual(self.slots().data, ["12:00", "14:00", "16:00", "18:00", "20:00"])
        self.assertEqual(self.book(time="14:00").data["local_end_time"], "16:00")

    def test_inheritance_branch_then_type_then_platform(self):
        self.assertEqual(rules.rules_for(self.branch)["slot_minutes"], 30)
        self.tenant.business_types = ["beauty_salon"]
        self.tenant.save()
        self.branch.refresh_from_db()
        self.assertEqual(rules.rules_for(self.branch)["duration_minutes"], 60)  # built in for salons
        res = api(self.root).put(
            PLATFORM, {"default": {"slot_minutes": 45, "lead_minutes": 10}, "by_type": {"beauty_salon": {"slot_minutes": 20}}},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        got = rules.rules_for(self.branch)
        self.assertEqual((got["slot_minutes"], got["lead_minutes"], got["duration_minutes"]), (20, 10, 60))
        view = self.put(slot_minutes=15).data
        self.assertEqual((view["effective"]["slot_minutes"], view["inherited"]["slot_minutes"]), (15, 20))
        self.assertEqual(self.put(slot_minutes="").data["effective"]["slot_minutes"], 20)  # cleared
        self.assertEqual(PlatformSettingChange.objects.filter(key=rules.SETTINGS_KEY).count(), 1)

    def test_validation_and_permissions(self):
        for bad in ({"slot_minutes": 4}, {"duration_minutes": 1441}, {"max_concurrent": 0}, {"lead_minutes": "x"}, {"slot_minutes": 1.5}):
            self.assertEqual(self.put(**bad).status_code, 400, bad)
        waiter = make_user()
        assign_role(waiter, self.tenant, "waiter", branch=self.branch)
        self.assertEqual(api(waiter).get(self.url).status_code, 200)
        self.assertEqual(self.put(waiter, slot_minutes=60).status_code, 403)
        outsider, _ = make_tenant_with_owner()
        self.assertEqual(api(outsider).get(self.url).status_code, 403)
        self.assertEqual(api(self.owner).get(PLATFORM).status_code, 403)
        self.assertEqual(api(self.root).put(PLATFORM, {"by_type": {"zoo": {}}}, format="json").status_code, 400)

    def test_concurrent_limit(self):
        self.put(slot_minutes=60, duration_minutes=60, max_concurrent=2)
        for _ in range(2):
            self.assertEqual(self.book(make_user(), time="15:00").status_code, 201)
        self.assertNotIn("15:00", self.slots().data)
        self.assertIn("16:00", self.slots().data)
        self.assertEqual(self.book(time="15:00").status_code, 400)

    def test_changing_rules_keeps_existing_reservations(self):
        self.book()
        self.put(duration_minutes=30)
        self.assertEqual(Reservation.objects.get().duration_minutes, 120)


class DurationTests(Base):
    def setUp(self):
        super().setUp()
        rules.save_branch_rules(self.branch, {"slot_minutes": 60, "duration_minutes": 60, "max_concurrent": 1}, actor=None)
        self.a = self.make(13)

    def make(self, hour, status=ReservationStatus.CONFIRMED, minutes=60):
        return Reservation.objects.create(
            branch=self.branch, customer=self.customer, guest_name="Ali", guest_phone="0912", party_size=2, status=status,
            reserved_at=datetime.combine(self.day, time(hour), tzinfo=branch_zone(self.branch)), duration_minutes=minutes,
        )

    def change(self, minutes, user=None, r=None):
        return api(user or self.owner).patch(
            f"/api/reservations/{(r or self.a).id}/duration/", {"duration_minutes": minutes}, format="json"
        )

    def test_extend_only_into_free_time(self):
        self.make(16)
        detail = f"/api/reservations/console-reservations/tenants/{self.tenant.id}/{self.a.id}/"
        self.assertEqual(api(self.owner).get(detail).data["max_duration_minutes"], 180)
        self.assertEqual(self.change(181).status_code, 400)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.change(180)
        self.assertEqual((res.status_code, res.data["local_end_time"]), (200, "16:00"))
        self.assertEqual(self.slots().data, ["12:00", "17:00", "18:00", "19:00", "20:00", "21:00"])
        n = Notification.objects.get(recipient=self.customer, type="reservation_duration_changed")
        self.assertEqual(n.data["until"], "16:00")

    def test_shorten_frees_the_time(self):
        self.change(240)
        self.assertNotIn("15:00", self.slots().data)
        self.assertEqual(self.change(90).status_code, 200)
        self.assertIn("15:00", self.slots().data)
        self.assertNotIn("14:00", self.slots().data)

    def test_cancelled_neighbour_does_not_block(self):
        self.make(14, ReservationStatus.CANCELLED)
        self.assertEqual(self.change(120).status_code, 200)

    def test_guest_capacity_also_limits(self):
        rules.save_branch_rules(self.branch, {"slot_minutes": 60, "duration_minutes": 60}, actor=None)
        self.branch.max_capacity = 5
        self.branch.save()
        Reservation.objects.filter(id=self.make(15).id).update(party_size=4)
        self.assertEqual(self.change(150).status_code, 400)
        self.assertEqual(self.change(120).status_code, 200)

    def test_no_limits_means_always_free(self):
        rules.save_branch_rules(self.branch, {}, actor=None)
        self.make(14)
        self.assertEqual(self.change(600).status_code, 200)

    def test_who_and_when(self):
        self.assertEqual(self.change(30, self.customer).status_code, 403)
        manager, support = make_user(), make_user()
        assign_role(manager, self.tenant, "manager", branch=self.branch)
        assign_role(support, self.tenant, "support", branch=self.branch)
        self.assertEqual(self.change(30, manager).status_code, 200)
        self.assertEqual(self.change(45, support).status_code, 403)
        for status in (ReservationStatus.COMPLETED, ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW):
            self.assertEqual(self.change(45, r=self.make(18, status)).status_code, 400)
        self.assertEqual(self.change(4).status_code, 400)

    def test_ends_at_follows(self):
        self.assertEqual(self.a.ends_at, self.a.reserved_at + timedelta(minutes=60))
