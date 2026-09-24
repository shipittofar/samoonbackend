"""HTTP management APIs and Django Admin for QR codes."""
from __future__ import annotations

from django.contrib import admin
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from access.tests.helpers import make_branch, make_tenant, make_user
from tenants.admin.qr import QrCodeAdmin
from tenants.models import QrCode
from tenants.models.qr_code import QrDestinationType, QrEntityType


def _auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@override_settings(PUBLIC_SITE_URL="http://frontend.test")
class TenantQrManagementAPITests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant()
        self.other_owner, self.other_tenant = make_tenant()
        self.qr = QrCode.objects.get(
            entity_type=QrEntityType.TENANT,
            entity_id=self.tenant.id,
            is_active=True,
        )
        self.client = _auth_client(self.owner)
        self.other = _auth_client(self.other_owner)
        self.url = f"/api/tenants/{self.tenant.id}/qr/"

    def test_owner_retrieves_own_tenant_qr(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], self.qr.code)
        self.assertEqual(response.data["entity_type"], "tenant")
        self.assertEqual(response.data["entity_id"], str(self.tenant.id))
        self.assertEqual(response.data["destination_type"], "tenant")
        self.assertTrue(response.data["is_active"])
        self.assertTrue(response.data["url"].endswith(f"/qr/{self.qr.code}"))
        self.assertIn("/qr/", response.data["url"])

    def test_unauthenticated_retrieve_rejected(self):
        response = APIClient().get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_other_owner_cannot_retrieve(self):
        response = self.other.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "unauthorized_qr_access")

    def test_owner_can_disable_and_resolver_returns_410(self):
        response = self.client.post(f"{self.url}disable/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.assertEqual(response.data["code"], self.qr.code)

        public = APIClient().get(f"/qr/{self.qr.code}/")
        self.assertEqual(public.status_code, 410)
        self.assertEqual(public.data["error"]["code"], "qr_disabled")

        missing = self.client.get(self.url)
        self.assertEqual(missing.status_code, 404)

    def test_other_owner_cannot_disable(self):
        response = self.other.post(f"{self.url}disable/")
        self.assertEqual(response.status_code, 403)
        self.qr.refresh_from_db()
        self.assertTrue(self.qr.is_active)

    def test_owner_can_enable_after_disable(self):
        self.client.post(f"{self.url}disable/")
        response = self.client.post(f"{self.url}enable/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["code"], self.qr.code)
        public = APIClient().get(f"/qr/{self.qr.code}/")
        self.assertEqual(public.status_code, 302)

    def test_other_owner_cannot_enable(self):
        self.client.post(f"{self.url}disable/")
        response = self.other.post(f"{self.url}enable/")
        self.assertEqual(response.status_code, 403)

    def test_owner_regenerate_issues_new_code(self):
        old_code = self.qr.code
        dest = self.qr.destination_type
        response = self.client.post(f"{self.url}regenerate/")
        self.assertEqual(response.status_code, 200)
        new_code = response.data["code"]
        self.assertNotEqual(new_code, old_code)
        self.assertTrue(response.data["is_active"])
        self.assertTrue(response.data["url"].endswith(f"/qr/{new_code}"))
        self.assertFalse(response.data["url"].endswith(f"/qr/{old_code}"))
        self.assertEqual(response.data["entity_id"], str(self.tenant.id))
        self.assertEqual(response.data["destination_type"], dest)

        self.assertEqual(APIClient().get(f"/qr/{old_code}/").status_code, 410)
        self.assertEqual(APIClient().get(f"/qr/{new_code}/").status_code, 302)

    def test_other_owner_cannot_regenerate(self):
        response = self.other.post(f"{self.url}regenerate/")
        self.assertEqual(response.status_code, 403)
        self.qr.refresh_from_db()
        self.assertTrue(self.qr.is_active)

    def test_tenant_destination_stays_tenant(self):
        old_code = self.qr.code
        response = self.client.patch(
            f"{self.url}destination/",
            {"destination_type": "menu"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], old_code)
        self.assertEqual(response.data["destination_type"], "tenant")

    def test_invalid_destination_rejected(self):
        response = self.client.patch(
            f"{self.url}destination/",
            {"destination_type": "campaign"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)


@override_settings(PUBLIC_SITE_URL="http://frontend.test")
class BranchQrManagementAPITests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant, name="QR Branch")
        self.other_owner, self.other_tenant = make_tenant()
        self.other_branch = make_branch(self.other_tenant)
        self.qr = QrCode.objects.get(
            entity_type=QrEntityType.BRANCH,
            entity_id=self.branch.id,
            is_active=True,
        )
        self.client = _auth_client(self.owner)
        self.other = _auth_client(self.other_owner)
        self.url = f"/api/branches/{self.branch.id}/qr/"

    def test_owner_retrieves_own_branch_qr(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], self.qr.code)
        self.assertEqual(response.data["entity_type"], "branch")
        self.assertEqual(response.data["entity_id"], str(self.branch.id))

    def test_other_owner_cannot_retrieve_branch_qr(self):
        response = self.other.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_owner_can_disable_branch_qr(self):
        response = self.client.post(f"{self.url}disable/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.assertEqual(APIClient().get(f"/qr/{self.qr.code}/").status_code, 410)

    def test_other_owner_cannot_disable_branch_qr(self):
        response = self.other.post(f"{self.url}disable/")
        self.assertEqual(response.status_code, 403)

    def test_owner_can_enable_branch_qr(self):
        self.client.post(f"{self.url}disable/")
        response = self.client.post(f"{self.url}enable/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_active"])

    def test_other_owner_cannot_enable_branch_qr(self):
        self.client.post(f"{self.url}disable/")
        response = self.other.post(f"{self.url}enable/")
        self.assertEqual(response.status_code, 403)

    def test_branch_destination_change_keeps_code(self):
        old_code = self.qr.code
        response = self.client.patch(
            f"{self.url}destination/",
            {"destination_type": QrDestinationType.MENU},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], old_code)
        self.assertEqual(response.data["destination_type"], "menu")
        public = APIClient().get(f"/qr/{old_code}/")
        self.assertEqual(public.status_code, 302)
        self.assertTrue(public["Location"].endswith("/menu"))

    def test_branch_regenerate_preserves_entity_and_destination(self):
        self.client.patch(
            f"{self.url}destination/",
            {"destination_type": "reservation"},
            format="json",
        )
        old_code = QrCode.objects.get(
            entity_type=QrEntityType.BRANCH,
            entity_id=self.branch.id,
            is_active=True,
        ).code
        response = self.client.post(f"{self.url}regenerate/")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["code"], old_code)
        self.assertEqual(response.data["entity_id"], str(self.branch.id))
        self.assertEqual(response.data["destination_type"], "reservation")
        self.assertEqual(APIClient().get(f"/qr/{old_code}/").status_code, 410)
        self.assertEqual(
            APIClient().get(f"/qr/{response.data['code']}/").status_code, 302
        )

    def test_invalid_branch_destination_rejected(self):
        response = self.client.patch(
            f"{self.url}destination/",
            {"destination_type": "orders"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)


@override_settings(PUBLIC_SITE_URL="http://frontend.test")
class MenuQrManagementAPITests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant, name="Menu QR Branch")
        self.other_owner, self.other_tenant = make_tenant()
        self.other_branch = make_branch(self.other_tenant)
        self.qr = QrCode.objects.get(
            entity_type=QrEntityType.MENU,
            entity_id=self.branch.id,
            is_active=True,
        )
        self.client = _auth_client(self.owner)
        self.other = _auth_client(self.other_owner)
        self.url = f"/api/menu/branches/{self.branch.id}/qr/"

    def test_owner_retrieves_own_menu_qr(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], self.qr.code)
        self.assertEqual(response.data["entity_type"], "menu")
        self.assertEqual(response.data["entity_id"], str(self.branch.id))
        self.assertEqual(response.data["destination_type"], "menu")
        self.assertTrue(response.data["url"].endswith(f"/qr/{self.qr.code}"))

    def test_unauthenticated_retrieve_rejected(self):
        response = APIClient().get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_other_owner_cannot_retrieve(self):
        response = self.other.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_owner_can_disable_and_resolver_returns_410(self):
        response = self.client.post(f"{self.url}disable/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.assertEqual(APIClient().get(f"/qr/{self.qr.code}/").status_code, 410)

    def test_other_owner_cannot_disable(self):
        response = self.other.post(f"{self.url}disable/")
        self.assertEqual(response.status_code, 403)

    def test_owner_can_enable_after_disable(self):
        self.client.post(f"{self.url}disable/")
        response = self.client.post(f"{self.url}enable/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["code"], self.qr.code)

    def test_other_owner_cannot_enable(self):
        self.client.post(f"{self.url}disable/")
        response = self.other.post(f"{self.url}enable/")
        self.assertEqual(response.status_code, 403)

    def test_owner_regenerate_issues_new_code(self):
        old_code = self.qr.code
        response = self.client.post(f"{self.url}regenerate/")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["code"], old_code)
        self.assertEqual(response.data["entity_type"], "menu")
        self.assertEqual(response.data["entity_id"], str(self.branch.id))
        self.assertEqual(response.data["destination_type"], "menu")
        self.assertTrue(response.data["url"].endswith(f"/qr/{response.data['code']}"))
        self.assertEqual(APIClient().get(f"/qr/{old_code}/").status_code, 410)
        public = APIClient().get(f"/qr/{response.data['code']}/")
        self.assertEqual(public.status_code, 302)
        self.assertTrue(public["Location"].endswith("/menu"))

    def test_destination_endpoint_not_exposed(self):
        response = self.client.patch(
            f"{self.url}destination/",
            {"destination_type": "branch"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_enable_rejected(self):
        self.client.post(f"{self.url}disable/")
        response = APIClient().post(f"{self.url}enable/")
        self.assertEqual(response.status_code, 401)
        self.qr.refresh_from_db()
        self.assertFalse(self.qr.is_active)

    def test_enable_persists_active_state(self):
        self.client.post(f"{self.url}disable/")
        response = self.client.post(f"{self.url}enable/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.qr.refresh_from_db()
        self.assertTrue(self.qr.is_active)
        self.assertEqual(self.qr.entity_type, QrEntityType.MENU)
        self.assertEqual(self.qr.entity_id, self.branch.id)
        self.assertEqual(
            QrCode.objects.filter(
                entity_type=QrEntityType.MENU,
                entity_id=self.branch.id,
                is_active=True,
            ).count(),
            1,
        )

    def test_enable_ignores_unrecognized_body(self):
        """Enable takes no fields; extra JSON must not become a 500."""
        self.client.post(f"{self.url}disable/")
        response = self.client.post(
            f"{self.url}enable/",
            {"is_active": "yes", "tenant_id": "not-a-uuid"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_active"])

    def test_missing_branch_returns_not_found(self):
        import uuid

        response = self.client.post(
            f"/api/menu/branches/{uuid.uuid4()}/qr/enable/"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "branch_not_found")

    def test_non_uuid_branch_is_not_routed(self):
        response = self.client.post("/api/menu/branches/not-a-branch/qr/enable/")
        self.assertEqual(response.status_code, 404)

    def test_other_tenant_header_does_not_grant_access(self):
        self.client.post(f"{self.url}disable/")
        self.other.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        response = self.other.post(f"{self.url}enable/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "unauthorized_qr_access")
        self.qr.refresh_from_db()
        self.assertFalse(self.qr.is_active)

    def test_owner_does_not_require_tenant_header(self):
        self.client.post(f"{self.url}disable/")
        response = self.client.post(f"{self.url}enable/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_active"])

    def test_menu_category_list_still_works_after_enable(self):
        self.client.post(f"{self.url}disable/")
        self.client.post(f"{self.url}enable/")
        response = self.client.get(
            f"/api/menu/categories/{self.branch.id}/"
        )
        self.assertEqual(response.status_code, 200)


@override_settings(PUBLIC_SITE_URL="http://frontend.test")
class ReservationQrManagementAPITests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant, name="Reservation QR Branch")
        self.other_owner, _ = make_tenant()
        self.qr = QrCode.objects.get(
            entity_type=QrEntityType.RESERVATION,
            entity_id=self.branch.id,
            is_active=True,
        )
        self.client = _auth_client(self.owner)
        self.other = _auth_client(self.other_owner)
        self.url = f"/api/reservations/branches/{self.branch.id}/qr/"

    def test_owner_retrieves_own_reservation_qr(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], self.qr.code)
        self.assertEqual(response.data["entity_type"], "reservation")
        self.assertEqual(response.data["entity_id"], str(self.branch.id))
        self.assertEqual(response.data["destination_type"], "reservation")

    def test_other_owner_cannot_retrieve(self):
        response = self.other.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_owner_can_disable(self):
        response = self.client.post(f"{self.url}disable/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(APIClient().get(f"/qr/{self.qr.code}/").status_code, 410)

    def test_owner_regenerate_preserves_reservation_entity(self):
        old_code = self.qr.code
        response = self.client.post(f"{self.url}regenerate/")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["code"], old_code)
        self.assertEqual(response.data["entity_type"], "reservation")
        self.assertEqual(response.data["destination_type"], "reservation")
        public = APIClient().get(f"/qr/{response.data['code']}/")
        self.assertEqual(public.status_code, 302)
        self.assertTrue(public["Location"].endswith("/reservation"))

    def test_unauthenticated_retrieve_rejected(self):
        response = APIClient().get(self.url)
        self.assertEqual(response.status_code, 401)


class QrCodeAdminTests(TestCase):
    def test_qr_code_is_registered(self):
        self.assertIn(QrCode, admin.site._registry)
        model_admin = admin.site._registry[QrCode]
        self.assertIsInstance(model_admin, QrCodeAdmin)
        self.assertEqual(
            tuple(model_admin.search_fields),
            ("code",),
        )
        self.assertEqual(
            tuple(model_admin.list_filter),
            ("entity_type", "destination_type", "is_active"),
        )
        self.assertIn("enable_qr_codes", model_admin.actions)
        self.assertIn("disable_qr_codes", model_admin.actions)
        self.assertIn("regenerate_qr_codes", model_admin.actions)
        self.assertFalse(model_admin.has_add_permission(None))

    def test_superuser_can_disable_via_admin_action(self):
        _, tenant = make_tenant()
        qr = QrCode.objects.get(
            entity_type=QrEntityType.TENANT, entity_id=tenant.id, is_active=True
        )
        superuser = make_user()
        superuser.is_staff = True
        superuser.is_superuser = True
        superuser.save()

        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage

        rf_request = RequestFactory().post("/admin/")
        rf_request.user = superuser
        rf_request.session = {}
        setattr(rf_request, "_messages", FallbackStorage(rf_request))

        model_admin = QrCodeAdmin(QrCode, admin.site)
        queryset = QrCode.objects.filter(pk=qr.pk)
        model_admin.disable_qr_codes(rf_request, queryset)
        qr.refresh_from_db()
        self.assertFalse(qr.is_active)
        self.assertEqual(APIClient().get(f"/qr/{qr.code}/").status_code, 410)

    def test_superuser_regenerate_admin_action_changes_code(self):
        _, tenant = make_tenant()
        qr = QrCode.objects.get(
            entity_type=QrEntityType.TENANT, entity_id=tenant.id, is_active=True
        )
        old_code = qr.code
        superuser = make_user()
        superuser.is_staff = True
        superuser.is_superuser = True
        superuser.save()

        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage

        rf_request = RequestFactory().post("/admin/")
        rf_request.user = superuser
        rf_request.session = {}
        setattr(rf_request, "_messages", FallbackStorage(rf_request))

        model_admin = QrCodeAdmin(QrCode, admin.site)
        model_admin.regenerate_qr_codes(
            rf_request, QrCode.objects.filter(pk=qr.pk)
        )
        qr.refresh_from_db()
        self.assertFalse(qr.is_active)
        new_qr = QrCode.objects.get(
            entity_type=QrEntityType.TENANT,
            entity_id=tenant.id,
            is_active=True,
        )
        self.assertNotEqual(new_qr.code, old_code)
