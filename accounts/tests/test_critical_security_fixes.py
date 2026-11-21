"""Regression tests for the critical security fixes.

1. Menu extras / extra groups: no anonymous or cross-branch writes.
2. Sign-up requires a real, recent, unspent OTP verification of that identifier.
3. Permission overrides: no self-grants, no granting what you don't hold, no
   platform permissions per tenant; global role definitions are superuser-only.
4. The user list/detail (everyone's phone/email) is superuser-only.
5. Anonymous auth endpoints are rate limited per client IP.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from access.models import Permission, PermissionOverride, Role
from access.tests.helpers import (
    create_canonical_assignment,
    make_branch,
    make_membership,
    make_tenant,
    make_user,
)
from accounts.models import OTPCode, OTPType, User
from menu.models import Extra, ExtraGroup


# ── 1. menu extras ──────────────────────────────────────────────────────────

class MenuExtrasWriteProtectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.extra = Extra.objects.create(branch=self.branch, name="Cheese", price=Decimal("1.00"))
        self.group = ExtraGroup.objects.create(branch=self.branch, name="Sauces")
        _, self.other_tenant = make_tenant()
        self.other_branch = make_branch(self.other_tenant)

    def test_anonymous_cannot_create_update_or_delete_extras(self):
        create = self.client.post(
            "/api/menu/create-extras/",
            {"branch_id": str(self.branch.id), "name": "Hacked", "price": "0.01"},
            format="json",
        )
        update = self.client.patch(
            f"/api/menu/update-extera/{self.branch.id}/extras/{self.extra.id}/",
            {"price": "0.01"},
            format="json",
        )
        delete = self.client.delete(f"/api/menu/delete-exteras/{self.branch.id}/extras/{self.extra.id}/")
        for response in (create, update, delete):
            self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.extra.refresh_from_db()
        self.assertEqual(self.extra.price, Decimal("1.00"))
        self.assertFalse(Extra.objects.filter(name="Hacked").exists())

    def test_anonymous_cannot_write_extra_groups(self):
        create = self.client.post(
            "/api/menu/create-extra-groups/",
            {"branch_id": str(self.branch.id), "name": "Hacked"},
            format="json",
        )
        delete = self.client.delete(
            f"/api/menu/delete-extra-groups/{self.branch.id}/extra-groups/{self.group.id}/"
        )
        for response in (create, delete):
            self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertTrue(ExtraGroup.objects.filter(id=self.group.id).exists())

    def test_alias_endpoints_stay_public_for_reads_but_not_writes(self):
        read = self.client.get(f"/api/menu/extras/?branch_id={self.branch.id}")
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        write = self.client.post(
            "/api/menu/extras/",
            {"branch_id": str(self.branch.id), "name": "Hacked", "price": "0.01"},
            format="json",
        )
        self.assertIn(write.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_owner_can_manage_own_branch_extras(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/menu/create-extras/",
            {"branch_id": str(self.branch.id), "name": "Olives", "price": "2.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_another_tenants_owner_cannot_touch_this_branch(self):
        stranger, _ = make_tenant()
        self.client.force_authenticate(stranger)
        response = self.client.patch(
            f"/api/menu/update-extera/{self.branch.id}/extras/{self.extra.id}/",
            {"price": "0.01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authorised_on_one_branch_cannot_edit_another_branchs_extra(self):
        # Owner of the other tenant passes the check for THEIR branch id, but the
        # extra belongs to this branch: lookups are scoped by (id, branch).
        other_owner = User.objects.get(id=self.other_tenant.owner.user_id)
        self.client.force_authenticate(other_owner)
        response = self.client.patch(
            f"/api/menu/update-extera/{self.other_branch.id}/extras/{self.extra.id}/",
            {"price": "0.01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.extra.refresh_from_db()
        self.assertEqual(self.extra.price, Decimal("1.00"))

    def test_console_menu_lists_need_branch_permission(self):
        stranger = make_user()
        self.client.force_authenticate(stranger)
        response = self.client.get(f"/api/menu/console-menu/extra-groups/{self.branch.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ── 2. sign-up requires real OTP verification ──────────────────────────────

PHONE = {"country_code": "+98", "phone_number": "9121234567"}
FULL_PHONE = "+989121234567"


class SignupRequiresVerifiedOtpTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def send(self):
        return self.client.post("/api/auth/send-otp/", PHONE, format="json")

    def latest_code(self):
        return OTPCode.objects.filter(identifier=FULL_PHONE).order_by("-created_at").first()

    def register(self):
        return self.client.post("/api/auth/register/", {**PHONE, "first_name": "Ali"}, format="json")

    def test_superseded_code_does_not_count_as_verification(self):
        # The attack: request a code twice so the first one is marked used.
        self.send()
        self.send()
        self.assertTrue(OTPCode.objects.filter(identifier=FULL_PHONE, is_used=True).exists())
        response = self.register()
        self.assertNotEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(User.all_objects.filter(phone_number=FULL_PHONE).exists())

    def test_exhausted_code_does_not_count_as_verification(self):
        self.send()
        for _ in range(OTPCode.MAX_ATTEMPTS):
            self.client.post("/api/auth/verify-otp/", {**PHONE, "code": "000000"}, format="json")
        self.assertTrue(self.latest_code().is_used)
        self.assertNotEqual(self.register().status_code, status.HTTP_201_CREATED)

    def test_correct_code_then_register_works_once(self):
        self.send()
        verify = self.client.post(
            "/api/auth/verify-otp/", {**PHONE, "code": self.latest_code().code}, format="json"
        )
        self.assertEqual(verify.status_code, status.HTTP_200_OK)
        self.assertTrue(verify.json()["is_new_user"])
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)
        # the same verification cannot create a second account
        User.objects.filter(phone_number=FULL_PHONE).delete()
        self.assertNotEqual(self.register().status_code, status.HTTP_201_CREATED)

    def test_verification_expires(self):
        self.send()
        self.client.post("/api/auth/verify-otp/", {**PHONE, "code": self.latest_code().code}, format="json")
        OTPCode.objects.filter(identifier=FULL_PHONE).update(verified_at=timezone.now() - timedelta(hours=1))
        self.assertNotEqual(self.register().status_code, status.HTTP_201_CREATED)


# ── 3. permission overrides and global roles ───────────────────────────────

class OverrideEscalationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.manager = make_user()
        self.manager_membership = make_membership(user=self.manager, tenant=self.tenant)
        create_canonical_assignment(
            membership=self.manager_membership,
            role=Role.objects.get(slug="manager"),
            all_locations=True,
        )
        self.waiter = make_user()
        self.waiter_membership = make_membership(user=self.waiter, tenant=self.tenant)
        self.url = f"/api/authorization/tenants/{self.tenant.id}/permission-overrides/"

    def grant(self, actor, membership, slug, effect="allow"):
        self.client.force_authenticate(actor)
        return self.client.post(
            self.url,
            {
                "membership_id": str(membership.id),
                "permission_id": str(Permission.objects.get(slug=slug).id),
                "effect": effect,
            },
            format="json",
        )

    def test_manager_cannot_grant_themselves_anything(self):
        response = self.grant(self.manager, self.manager_membership, "tenant.manage")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(PermissionOverride.objects.exists())

    def test_manager_cannot_grant_what_they_do_not_hold(self):
        response = self.grant(self.manager, self.waiter_membership, "tenant.manage")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_can_grant_what_they_hold(self):
        response = self.grant(self.manager, self.waiter_membership, "orders.view")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_nobody_grants_platform_role_management_inside_a_tenant(self):
        response = self.grant(self.owner, self.waiter_membership, "rbac.manage_roles")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_remove_a_deny_on_yourself(self):
        deny = PermissionOverride.objects.create(
            membership=self.manager_membership,
            permission=Permission.objects.get(slug="orders.cancel"),
            effect="deny",
            created_by=self.owner,
        )
        self.client.force_authenticate(self.manager)
        response = self.client.delete(f"{self.url}{deny.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(PermissionOverride.objects.filter(id=deny.id).exists())

    def test_global_role_definitions_are_superuser_only(self):
        waiter_role = Role.objects.get(slug="waiter")
        url = f"/api/authorization/roles/{waiter_role.id}/permissions/"
        everything = [str(p.id) for p in Permission.objects.all()]
        for actor in (self.owner, self.manager, make_user(is_staff=True)):
            self.client.force_authenticate(actor)
            response = self.client.put(url, {"permission_ids": everything}, format="json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, actor)
        superuser = make_user(is_staff=True, is_superuser=True)
        self.client.force_authenticate(superuser)
        self.assertEqual(
            self.client.put(url, {"permission_ids": everything}, format="json").status_code,
            status.HTTP_200_OK,
        )


# ── 4. user list ──────────────────────────────────────────────────────────

class UserListIsSuperuserOnlyTests(TestCase):
    def test_regular_and_staff_users_cannot_list_users(self):
        client = APIClient()
        target = make_user()
        for actor in (make_user(), make_user(is_staff=True)):
            client.force_authenticate(actor)
            self.assertEqual(client.get("/api/auth/users/").status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(client.get(f"/api/auth/users/{target.id}/").status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_can_list_users(self):
        client = APIClient()
        client.force_authenticate(make_user(is_staff=True, is_superuser=True))
        self.assertEqual(client.get("/api/auth/users/").status_code, status.HTTP_200_OK)


# ── 5. auth rate limits ────────────────────────────────────────────────────

class AuthRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_password_login_is_throttled_per_ip(self):
        from rest_framework.throttling import ScopedRateThrottle

        original = ScopedRateThrottle.THROTTLE_RATES
        ScopedRateThrottle.THROTTLE_RATES = {**original, "auth_password_login": "3/hour"}
        try:
            client = APIClient()
            body = {"email": "nobody@example.com", "password": "wrong-password"}
            codes = [client.post("/api/auth/password-login/", body, format="json").status_code for _ in range(4)]
        finally:
            ScopedRateThrottle.THROTTLE_RATES = original
        self.assertNotIn(status.HTTP_429_TOO_MANY_REQUESTS, codes[:3])
        self.assertEqual(codes[3], status.HTTP_429_TOO_MANY_REQUESTS)

    def test_spoofed_forwarded_for_does_not_reset_the_limit(self):
        from rest_framework.throttling import ScopedRateThrottle

        original = ScopedRateThrottle.THROTTLE_RATES
        ScopedRateThrottle.THROTTLE_RATES = {**original, "auth_password_login": "2/hour"}
        try:
            client = APIClient()
            body = {"email": "nobody@example.com", "password": "wrong-password"}
            codes = [
                client.post(
                    "/api/auth/password-login/",
                    body,
                    format="json",
                    # what a client sends; nginx appends the real address last
                    HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.7",
                ).status_code
                for i in range(3)
            ]
        finally:
            ScopedRateThrottle.THROTTLE_RATES = original
        self.assertEqual(api_settings.NUM_PROXIES, 1)
        self.assertEqual(codes[2], status.HTTP_429_TOO_MANY_REQUESTS)
