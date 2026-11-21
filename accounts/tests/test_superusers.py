"""Platform superusers: adding (admin_add), approval in the Django admin,
revoking, and "superuser = every permission everywhere; is_staff = nothing"."""
from __future__ import annotations

import io
import os
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from access.models import Permission
from access.services.rbac_bll import rbac_bll
from access.tests.helpers import make_branch, make_tenant, make_user
from accounts.models import PlatformSecuritySettings, SuperuserRequest, SuperuserRequestStatus, User
from accounts.services import superuser_bll
from core.exceptions import TenantPermissionDeniedException

PASSWORD = "Str0ng-Pass-2026!"


def run_admin_add(*args):
    out = io.StringIO()
    with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": PASSWORD}):
        call_command("admin_add", *args, "--no-input", stdout=out)
    return out.getvalue()


class NormalizePhoneTests(TestCase):
    def test_accepts_common_forms(self):
        for raw in ("09121234567", "9121234567", "+989121234567", "00989121234567",
                    "۰۹۱۲ ۱۲۳ ۴۵۶۷", "+98 912-123-4567"):
            self.assertEqual(superuser_bll.normalize_phone(raw).full, "+989121234567", raw)

    def test_rejects_garbage_and_foreign_without_country_code(self):
        for raw in ("abc", "12", "+4915112345678"):
            with self.assertRaises(superuser_bll.SuperuserError):
                superuser_bll.normalize_phone(raw)
        self.assertEqual(
            superuser_bll.normalize_phone("+4915112345678", "+49").full, "+4915112345678"
        )


class AdminAddCommandTests(TestCase):
    def test_first_superuser_is_created_directly(self):
        output = run_admin_add("09121234567", "--first-name", "Sara")
        user = User.objects.get(phone_number="+989121234567")
        self.assertTrue(user.is_superuser and user.is_staff and user.is_active)
        self.assertEqual(user.country_code, "+98")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertIn("first one", output)
        self.assertEqual(SuperuserRequest.objects.get(user=user).status, SuperuserRequestStatus.APPROVED)

    def test_existing_account_is_promoted_even_if_stored_with_trunk_zero(self):
        existing = make_user(phone_number="+9809121234567", country_code="+98")
        run_admin_add("+989121234567")
        existing.refresh_from_db()
        self.assertTrue(existing.is_superuser)
        self.assertEqual(User.objects.count(), 1)

    def test_later_superusers_are_refused_while_requests_are_off(self):
        run_admin_add("09121234567")
        with self.assertRaisesMessage(CommandError, "switched off"):
            run_admin_add("09351234567")
        self.assertFalse(User.objects.filter(phone_number="+989351234567").exists())

    def test_later_superusers_wait_for_approval(self):
        run_admin_add("09121234567")
        first = User.objects.get(phone_number="+989121234567")
        PlatformSecuritySettings.objects.filter(pk=1).update(allow_superuser_requests=True)

        output = run_admin_add("09351234567", "--note", "ops on-call")
        candidate = User.objects.get(phone_number="+989351234567")
        self.assertFalse(candidate.is_superuser or candidate.is_staff)
        self.assertIn("Request filed", output)
        request = SuperuserRequest.objects.get(user=candidate)
        self.assertEqual(request.status, SuperuserRequestStatus.PENDING)

        with self.assertRaisesMessage(CommandError, "pending"):
            run_admin_add("09351234567")

        superuser_bll.approve(request, actor=first)
        candidate.refresh_from_db()
        request.refresh_from_db()
        self.assertTrue(candidate.is_superuser and candidate.is_staff)
        self.assertEqual(request.decided_by, first)
        self.assertIsNotNone(request.decided_at)

    def test_running_again_for_a_superuser_changes_nothing(self):
        run_admin_add("09121234567")
        self.assertIn("already a superuser", run_admin_add("09121234567"))

    def test_weak_password_is_refused(self):
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": "123"}):
            with self.assertRaises(CommandError):
                call_command("admin_add", "09121234567", "--no-input", stdout=io.StringIO())
        self.assertFalse(User.objects.exists())

    def test_django_createsuperuser_only_works_for_the_first_one(self):
        User.objects.create_superuser(phone_number="+989121234567", password=PASSWORD)
        with self.assertRaisesMessage(ValueError, "admin_add"):
            User.objects.create_superuser(phone_number="+989351234567", password=PASSWORD)


class ApprovalRulesTests(TestCase):
    def setUp(self):
        self.root = make_user(is_superuser=True, is_staff=True)
        self.candidate = make_user()
        self.request = SuperuserRequest.objects.create(user=self.candidate)

    def test_only_superusers_decide(self):
        staff = make_user(is_staff=True)
        with self.assertRaises(superuser_bll.SuperuserError):
            superuser_bll.approve(self.request, actor=staff)
        with self.assertRaises(superuser_bll.SuperuserError):
            superuser_bll.approve(self.request, actor=self.candidate)

    def test_reject_then_cannot_approve(self):
        superuser_bll.reject(self.request, actor=self.root)
        with self.assertRaisesMessage(superuser_bll.SuperuserError, "already decided"):
            superuser_bll.approve(self.request, actor=self.root)
        self.candidate.refresh_from_db()
        self.assertFalse(self.candidate.is_superuser)

    def test_revoke_keeps_at_least_one_and_not_yourself(self):
        with self.assertRaisesMessage(superuser_bll.SuperuserError, "your own"):
            superuser_bll.revoke(self.root, actor=self.root)
        other = make_user(is_superuser=True, is_staff=True)
        superuser_bll.revoke(other, actor=self.root)
        other.refresh_from_db()
        self.assertFalse(other.is_superuser or other.is_staff)


class DjangoAdminTests(TestCase):
    def setUp(self):
        self.root = make_user(is_superuser=True, is_staff=True)
        self.client.force_login(self.root)

    def test_staff_without_superuser_cannot_open_the_admin(self):
        self.client.force_login(make_user(is_staff=True))
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_superuser_approves_in_the_admin(self):
        candidate = make_user()
        request = SuperuserRequest.objects.create(user=candidate)
        response = self.client.post(
            "/admin/accounts/superuserrequest/",
            {"action": "approve_selected", "_selected_action": [str(request.pk)]},
        )
        self.assertEqual(response.status_code, 302)
        candidate.refresh_from_db()
        self.assertTrue(candidate.is_superuser)

    def test_superuser_flag_cannot_be_edited_directly(self):
        target = make_user()
        page = self.client.get(f"/admin/accounts/user/{target.pk}/change/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="is_superuser"')

    def test_settings_page_and_requests_list_render(self):
        self.assertEqual(self.client.get("/admin/accounts/platformsecuritysettings/").status_code, 200)
        self.assertEqual(self.client.get("/admin/accounts/superuserrequest/").status_code, 200)


class SuperuserHasEveryPermissionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        self.root = make_user(is_superuser=True, is_staff=True)
        self.staff = make_user(is_staff=True)

    def test_effective_permissions_are_all_of_them(self):
        every = set(Permission.objects.values_list("slug", flat=True))
        self.assertEqual(rbac_bll.resolve_effective_permission_slugs(user=self.root, tenant=self.tenant), every)
        self.assertEqual(rbac_bll.resolve_effective_permission_slugs(user=self.staff, tenant=self.tenant), set())

    def test_tenant_endpoints_open_for_superuser_not_for_staff(self):
        url = f"/api/authorization/tenants/{self.tenant.id}/permission-overrides/"
        self.client.force_authenticate(self.root)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_branch_menu_writes_open_for_superuser_not_for_staff(self):
        body = {"branch_id": str(self.branch.id), "name": "Olives", "price": "2.00"}
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.client.post("/api/menu/create-extras/", body, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.client.force_authenticate(self.root)
        self.assertEqual(
            self.client.post("/api/menu/create-extras/", body, format="json").status_code,
            status.HTTP_201_CREATED,
        )

    def test_inactive_superuser_gets_nothing(self):
        self.root.is_active = False
        self.root.save(update_fields=["is_active"])
        self.assertEqual(rbac_bll.resolve_effective_permission_slugs(user=self.root, tenant=self.tenant), set())

    def test_tenant_ownership_check_no_longer_trusts_is_staff(self):
        from tenants.services.tenant_bll import _assert_owns_tenant

        tenant = type("T", (), {"owner_user_id": self.owner.id})()
        with self.assertRaises(TenantPermissionDeniedException):
            _assert_owns_tenant(self.staff, tenant)
        _assert_owns_tenant(self.root, tenant)
