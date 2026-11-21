"""Phase 3: one stored form per phone number, deleted accounts give their
number back, User.role is gone, and a suspended owner loses owner access."""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from access.services.rbac_bll import rbac_bll
from access.tests.helpers import make_branch, make_tenant, make_user
from accounts.models import OTPCode, User
from accounts.phone import InvalidPhoneNumber, full_phone
from accounts.services.profile_bll import AccountRestoreConflict, ProfileBusinessLogicLayer
from core.exceptions import TenantPermissionDeniedException
from tenants.models.tenant import OwnerStatus

FULL = "+989121234567"


class PhoneNormalizationTests(TestCase):
    def test_typed_forms_reach_one_stored_form(self):
        for raw in ("09121234567", "9121234567", "۰۹۱۲۱۲۳۴۵۶۷", "912 123 4567",
                    "912-123-4567", "+989121234567", "00989121234567"):
            self.assertEqual(full_phone("+98", raw), FULL, raw)

    def test_italy_keeps_its_leading_zero(self):
        self.assertEqual(full_phone("+39", "0612345678"), "+390612345678")

    def test_bad_input(self):
        for code, raw in (("+98", "abc"), ("+98", "12"), ("+98", "+4915112345678"), ("x", "912"), ("98", "9121234567")):
            with self.assertRaises(InvalidPhoneNumber):
                full_phone(code, raw)


class SignUpWithAnyFormTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def sign_up(self, typed: str):
        body = {"country_code": "+98", "phone_number": typed}
        self.client.post("/api/auth/send-otp/", body, format="json")
        code = OTPCode.objects.filter(identifier=FULL).order_by("-created_at").first()
        self.assertIsNotNone(code, "OTP was not issued for the normalized number")
        self.client.post("/api/auth/verify-otp/", {**body, "code": code.code}, format="json")
        return self.client.post("/api/auth/register/", {**body, "first_name": "Ali"}, format="json")

    def test_leading_zero_and_persian_digits_create_the_normal_form(self):
        response = self.sign_up("۰۹۱۲۱۲۳۴۵۶۷")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        user = User.objects.get(phone_number=FULL)
        self.assertEqual(user.country_code, "+98")

    def test_existing_account_is_found_whatever_the_form(self):
        make_user(phone_number=FULL, country_code="+98")
        self.client.post("/api/auth/send-otp/", {"country_code": "+98", "phone_number": "0912 123 4567"}, format="json")
        code = OTPCode.objects.filter(identifier=FULL).order_by("-created_at").first()
        verify = self.client.post(
            "/api/auth/verify-otp/",
            {"country_code": "+98", "phone_number": "09121234567", "code": code.code},
            format="json",
        )
        self.assertEqual(verify.status_code, status.HTTP_200_OK, verify.content)
        self.assertFalse(verify.json()["is_new_user"])
        self.assertEqual(User.all_objects.count(), 1)


class DeletedAccountTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_delete_frees_phone_and_email_and_signing_up_again_works(self):
        user = make_user(phone_number=FULL, country_code="+98", email="ali@example.com")
        self.client.force_authenticate(user)
        self.assertIn(self.client.delete("/api/auth/profile/delete/").status_code, (200, 204))
        user.refresh_from_db()
        self.assertTrue(user.is_deleted)
        self.assertIsNone(user.phone_number)
        self.assertIsNone(user.email)
        self.assertEqual(user.deleted_phone_number, FULL)
        self.assertEqual(user.deleted_email, "ali@example.com")

        self.client.force_authenticate(None)
        body = {"country_code": "+98", "phone_number": "9121234567"}
        self.client.post("/api/auth/send-otp/", body, format="json")
        code = OTPCode.objects.filter(identifier=FULL).order_by("-created_at").first()
        self.client.post("/api/auth/verify-otp/", {**body, "code": code.code}, format="json")
        response = self.client.post("/api/auth/register/", {**body, "first_name": "Ali"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertNotEqual(User.objects.get(phone_number=FULL).pk, user.pk)

    def test_restore_gives_the_number_back_unless_taken(self):
        user = make_user(phone_number=FULL, country_code="+98")
        ProfileBusinessLogicLayer.soft_delete(user)
        ProfileBusinessLogicLayer.restore(user)
        user.refresh_from_db()
        self.assertFalse(user.is_deleted)
        self.assertTrue(user.is_active)
        self.assertEqual(user.phone_number, FULL)

        ProfileBusinessLogicLayer.soft_delete(user)
        make_user(phone_number=FULL, country_code="+98")
        with self.assertRaises(AccountRestoreConflict):
            ProfileBusinessLogicLayer.restore(user)

    def test_admin_restore_action(self):
        root = make_user(is_superuser=True, is_staff=True)
        user = make_user(phone_number=FULL, country_code="+98")
        ProfileBusinessLogicLayer.soft_delete(user)
        self.client.force_login(root)
        response = self.client.post(
            "/admin/accounts/user/",
            {"action": "restore_selected_users", "_selected_action": [str(user.pk)]},
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.is_deleted)


class RoleFollowsSuperuserTests(TestCase):
    """role is derived: "admin" exactly when is_superuser is true."""

    def me(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client.get("/api/auth/me/").json()["user"]

    def test_superuser_is_admin_everyone_else_customer(self):
        self.assertEqual(self.me(make_user(is_superuser=True, is_staff=True))["role"], "admin")
        self.assertEqual(self.me(make_user())["role"], "customer")
        self.assertEqual(self.me(make_user(is_staff=True))["role"], "customer")

    def test_admin_add_gives_admin_and_revoke_takes_it_away(self):
        import io, os
        from unittest import mock
        from django.core.management import call_command
        from accounts.services import superuser_bll

        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": "Str0ng-Pass-2026!"}):
            call_command("admin_add", "09121234567", "--no-input", stdout=io.StringIO())
        root = User.objects.get(phone_number=FULL)
        self.assertEqual(root.role, "admin")

        other = make_user(is_superuser=True, is_staff=True)
        superuser_bll.revoke(other, actor=root)
        other.refresh_from_db()
        self.assertEqual(other.role, "customer")

    def test_user_endpoints_carry_role(self):
        root = make_user(is_superuser=True, is_staff=True)
        client = APIClient()
        client.force_authenticate(root)
        detail = client.get(f"/api/auth/users/{root.id}/").json()
        self.assertEqual(detail["role"], "admin")


class SuspendedOwnerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant)
        owner = self.tenant.owner
        owner.status = OwnerStatus.SUSPENDED
        owner.save(update_fields=["status"])

    def test_suspended_owner_loses_permissions_and_endpoints(self):
        self.assertEqual(
            rbac_bll.resolve_effective_permission_slugs(user=self.owner_user, tenant=self.tenant), set()
        )
        self.client.force_authenticate(self.owner_user)
        url = f"/api/authorization/tenants/{self.tenant.id}/permission-overrides/"
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_suspended_owner_cannot_edit_or_create_businesses(self):
        from tenants.services.tenant_bll import TenantBusinessLogicLayer, _assert_owns_tenant

        tenant = type("T", (), {"owner_user_id": self.owner_user.id})()
        with self.assertRaises(TenantPermissionDeniedException):
            _assert_owns_tenant(self.owner_user, tenant)
        with self.assertRaises(TenantPermissionDeniedException):
            TenantBusinessLogicLayer.create_tenant(self.owner_user, name="Second")

    def test_superuser_still_gets_in(self):
        root = make_user(is_superuser=True, is_staff=True)
        self.client.force_authenticate(root)
        url = f"/api/authorization/tenants/{self.tenant.id}/permission-overrides/"
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)

    def test_active_or_unset_status_is_unaffected(self):
        owner = self.tenant.owner
        for value in (None, OwnerStatus.ACTIVE, OwnerStatus.PENDING_VERIFICATION):
            owner.status = value
            owner.save(update_fields=["status"])
            self.assertTrue(
                rbac_bll.resolve_effective_permission_slugs(user=self.owner_user, tenant=self.tenant)
            )
