"""QR identifier generation, resolution, and tenant isolation."""
from __future__ import annotations

import uuid
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from access.tests.helpers import make_branch, make_tenant
from core.exceptions.qr import (
    QrDisabledException,
    QrNotFoundException,
    UnauthorizedQrAccessException,
)
from core.exceptions.tenant import BranchNotFoundException, TenantNotFoundException
from tenants.models import BranchStatus, QrCode, TenantStatus
from tenants.models.qr_code import QrDestinationType, QrEntityType
from tenants.services.public_url import (
    destination_path,
    qr_payload,
    qr_resolve_path,
)
from tenants.services.qr_bll import QrCodeBusinessLogicLayer


@override_settings(PUBLIC_SITE_URL="http://frontend.test")
class QrGenerationTests(TestCase):
    def test_tenant_create_assigns_unique_qr(self):
        _, tenant = make_tenant()
        qr = QrCode.objects.get(
            entity_type=QrEntityType.TENANT,
            entity_id=tenant.id,
            is_active=True,
        )
        self.assertEqual(len(qr.code), 8)
        self.assertTrue(qr.code.isalnum())
        self.assertEqual(qr.code, qr.code.lower())
        self.assertNotEqual(qr.code, str(tenant.id))
        self.assertNotEqual(qr.code, tenant.slug)

    def test_branch_create_assigns_qr_distinct_from_tenant(self):
        _, tenant = make_tenant()
        branch = make_branch(tenant)
        tenant_qr = QrCode.objects.get(
            entity_type=QrEntityType.TENANT, entity_id=tenant.id, is_active=True
        )
        branch_qr = QrCode.objects.get(
            entity_type=QrEntityType.BRANCH, entity_id=branch.id, is_active=True
        )
        self.assertNotEqual(tenant_qr.code, branch_qr.code)
        self.assertEqual(branch_qr.destination_type, QrDestinationType.BRANCH)

    def test_ensure_is_idempotent(self):
        _, tenant = make_tenant()
        first = QrCodeBusinessLogicLayer.ensure_for_tenant(tenant)
        second = QrCodeBusinessLogicLayer.ensure_for_tenant(tenant)
        self.assertEqual(first.id, second.id)
        self.assertEqual(
            QrCode.objects.filter(
                entity_type=QrEntityType.TENANT, entity_id=tenant.id, is_active=True
            ).count(),
            1,
        )

    def test_collision_retries_until_unique(self):
        _, tenant = make_tenant()
        existing = QrCode.objects.get(
            entity_type=QrEntityType.TENANT, entity_id=tenant.id, is_active=True
        )
        _, other = make_tenant()
        QrCode.objects.filter(
            entity_type=QrEntityType.TENANT, entity_id=other.id
        ).delete()

        codes = iter([existing.code, "zzzzzzzy"])
        with patch(
            "tenants.services.qr_bll.generate_random_slug",
            side_effect=lambda length=8: next(codes),
        ):
            created = QrCodeBusinessLogicLayer._create(
                entity_type=QrEntityType.TENANT,
                entity_id=other.id,
                destination_type=QrDestinationType.TENANT,
            )
        self.assertEqual(created.code, "zzzzzzzy")

    def test_exhausted_collisions_raise(self):
        _, tenant = make_tenant()
        existing = QrCode.objects.get(
            entity_type=QrEntityType.TENANT, entity_id=tenant.id, is_active=True
        )
        _, other = make_tenant()
        QrCode.objects.filter(
            entity_type=QrEntityType.TENANT, entity_id=other.id
        ).delete()

        with patch(
            "tenants.services.qr_bll.generate_random_slug",
            return_value=existing.code,
        ):
            with self.assertRaises(IntegrityError):
                QrCodeBusinessLogicLayer._create(
                    entity_type=QrEntityType.TENANT,
                    entity_id=other.id,
                    destination_type=QrDestinationType.TENANT,
                )


class PublicUrlTests(TestCase):
    def test_destination_paths(self):
        self.assertEqual(destination_path("tenant", tenant_slug="abc"), "/abc")
        self.assertEqual(
            destination_path("branch", tenant_slug="abc", branch_slug="xyz"),
            "/abc/xyz",
        )
        self.assertEqual(
            destination_path("menu", tenant_slug="abc", branch_slug="xyz"),
            "/abc/xyz/menu",
        )
        self.assertEqual(
            destination_path("reservation", tenant_slug="abc", branch_slug="xyz"),
            "/abc/xyz/reservation",
        )

    def test_qr_payload_uses_resolve_path_not_destination(self):
        payload = qr_payload("bi32b4if")
        self.assertEqual(payload["code"], "bi32b4if")
        self.assertEqual(payload["url"], qr_resolve_path("bi32b4if"))
        self.assertEqual(payload["url"], "/qr/bi32b4if")


@override_settings(PUBLIC_SITE_URL="http://frontend.test")
class QrResolutionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner, self.tenant = make_tenant()
        self.branch = make_branch(self.tenant, name="Main")
        self.tenant_qr = QrCode.objects.get(
            entity_type=QrEntityType.TENANT, entity_id=self.tenant.id, is_active=True
        )
        self.branch_qr = QrCode.objects.get(
            entity_type=QrEntityType.BRANCH, entity_id=self.branch.id, is_active=True
        )

    def test_tenant_qr_redirects_to_current_slug(self):
        response = self.client.get(f"/qr/{self.tenant_qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"http://frontend.test/{self.tenant.slug}",
        )

    def test_branch_qr_redirects_to_tenant_and_branch_slug(self):
        response = self.client.get(f"/qr/{self.branch_qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"http://frontend.test/{self.tenant.slug}/{self.branch.slug}",
        )

    def test_tenant_slug_change_keeps_qr_valid(self):
        self.tenant.slug = "new-tenant"
        self.tenant.save(update_fields=["slug", "updated_at"])
        response = self.client.get(f"/qr/{self.tenant_qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://frontend.test/new-tenant")

    def test_branch_slug_change_keeps_qr_valid(self):
        self.branch.slug = "new-branch"
        self.branch.save(update_fields=["slug", "updated_at"])
        response = self.client.get(f"/qr/{self.branch_qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"http://frontend.test/{self.tenant.slug}/new-branch",
        )

    def test_invalid_qr_returns_not_found(self):
        response = self.client.get("/qr/unknown1/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "qr_not_found")

    def test_disabled_qr_returns_gone(self):
        QrCodeBusinessLogicLayer.disable(self.owner, self.tenant_qr)
        response = self.client.get(f"/qr/{self.tenant_qr.code}/")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.data["error"]["code"], "qr_disabled")

    def test_inactive_tenant_does_not_redirect(self):
        self.tenant.is_active = False
        self.tenant.save(update_fields=["is_active", "updated_at"])
        response = self.client.get(f"/qr/{self.tenant_qr.code}/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "tenant_not_found")

    def test_inactive_branch_does_not_redirect(self):
        self.branch.is_active = False
        self.branch.status = BranchStatus.INACTIVE
        self.branch.save(update_fields=["is_active", "status", "updated_at"])
        response = self.client.get(f"/qr/{self.branch_qr.code}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "branch_not_found")

    def test_tenant_api_exposes_qr(self):
        response = self.client.get(f"/api/tenants/{self.tenant.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["qr"]["code"], self.tenant_qr.code)
        self.assertTrue(response.data["qr"]["url"].endswith(f"/qr/{self.tenant_qr.code}"))

    def test_branch_create_api_exposes_qr(self):
        client = APIClient()
        client.force_authenticate(user=self.owner)
        response = client.post(
            f"/api/branches/console-branches/tenants/{self.tenant.id}/create/",
            {"name": f"QR Branch {uuid.uuid4().hex[:6]}"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("qr", response.data)
        self.assertIsNotNone(response.data["qr"]["code"])
        self.assertTrue(
            QrCode.objects.filter(
                code=response.data["qr"]["code"],
                entity_type=QrEntityType.BRANCH,
                is_active=True,
            ).exists()
        )


@override_settings(PUBLIC_SITE_URL="http://frontend.test")
class QrManagementIsolationTests(TestCase):
    def setUp(self):
        self.owner_a, self.tenant_a = make_tenant()
        self.owner_b, self.tenant_b = make_tenant()
        self.qr_a = QrCode.objects.get(
            entity_type=QrEntityType.TENANT, entity_id=self.tenant_a.id, is_active=True
        )

    def test_other_tenant_cannot_disable_qr(self):
        with self.assertRaises(UnauthorizedQrAccessException):
            QrCodeBusinessLogicLayer.disable(self.owner_b, self.qr_a)
        self.qr_a.refresh_from_db()
        self.assertTrue(self.qr_a.is_active)

    def test_other_tenant_cannot_regenerate_qr(self):
        with self.assertRaises(UnauthorizedQrAccessException):
            QrCodeBusinessLogicLayer.regenerate(self.owner_b, self.qr_a)

    def test_owner_regenerate_deactivates_old_code(self):
        old_code = self.qr_a.code
        new_qr = QrCodeBusinessLogicLayer.regenerate(self.owner_a, self.qr_a)
        self.qr_a.refresh_from_db()
        self.assertFalse(self.qr_a.is_active)
        self.assertTrue(new_qr.is_active)
        self.assertNotEqual(new_qr.code, old_code)

        client = APIClient()
        gone = client.get(f"/qr/{old_code}/")
        self.assertEqual(gone.status_code, 410)
        ok = client.get(f"/qr/{new_qr.code}/")
        self.assertEqual(ok.status_code, 302)

    def test_changing_destination_keeps_code(self):
        branch = make_branch(self.tenant_a)
        qr = QrCode.objects.get(
            entity_type=QrEntityType.BRANCH, entity_id=branch.id, is_active=True
        )
        original = qr.code
        QrCodeBusinessLogicLayer.set_destination(
            self.owner_a, qr, QrDestinationType.MENU
        )
        qr.refresh_from_db()
        self.assertEqual(qr.code, original)
        self.assertEqual(qr.destination_type, QrDestinationType.MENU)
        response = APIClient().get(f"/qr/{qr.code}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"http://frontend.test/{self.tenant_a.slug}/{branch.slug}/menu",
        )


class QrResolverUnitTests(TestCase):
    def test_missing_code_raises(self):
        with self.assertRaises(QrNotFoundException):
            QrCodeBusinessLogicLayer.resolve_redirect_url("missing1")

    def test_disabled_raises(self):
        owner, tenant = make_tenant()
        qr = QrCode.objects.get(
            entity_type=QrEntityType.TENANT, entity_id=tenant.id, is_active=True
        )
        QrCodeBusinessLogicLayer.disable(owner, qr)
        with self.assertRaises(QrDisabledException):
            QrCodeBusinessLogicLayer.resolve_redirect_url(qr.code)

    def test_closed_tenant_raises(self):
        _, tenant = make_tenant()
        tenant.status = TenantStatus.CLOSED
        tenant.save(update_fields=["status", "updated_at"])
        qr = QrCode.objects.get(
            entity_type=QrEntityType.TENANT, entity_id=tenant.id, is_active=True
        )
        with self.assertRaises(TenantNotFoundException):
            QrCodeBusinessLogicLayer.resolve_redirect_url(qr.code)

    def test_missing_branch_raises(self):
        _, tenant = make_tenant()
        branch = make_branch(tenant)
        qr = QrCode.objects.get(
            entity_type=QrEntityType.BRANCH, entity_id=branch.id, is_active=True
        )
        code = qr.code
        branch.delete()
        with self.assertRaises(BranchNotFoundException):
            QrCodeBusinessLogicLayer.resolve_redirect_url(code)
