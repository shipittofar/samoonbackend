"""Regression tests for POST /api/users/addresses/ 500 fixes."""

import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from addresses.domain.verification import VerificationStatus
from addresses.models import AddressAuditLog
from addresses.services.address_domain_service import AddressDomainService
from addresses.services.audit_service import _json_safe
from addresses.tests.test_addresses import auth_client, make_user, valid_address_payload


class AuditJsonSafeTests(TestCase):
    def test_json_safe_converts_datetime(self):
        now = timezone.now()
        payload = {"verified_at": now, "nested": {"when": now}}
        safe = _json_safe(payload)
        self.assertIsInstance(safe["verified_at"], str)
        self.assertIsInstance(safe["nested"]["when"], str)


class AddressCreateRegressionTests(TestCase):
    def setUp(self):
        self.user = make_user(
            phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
            first_name="Jane",
            last_name="Doe",
            country_code="+1",
        )
        self.client = auth_client(self.user)

    def test_post_create_succeeds_with_auto_verification(self):
        response = self.client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["verification_status"], VerificationStatus.VERIFIED)
        self.assertTrue(response.data["is_verified"])
        self.assertIsNotNone(response.data["verified_at"])

    def test_create_writes_audit_log_with_verified_at(self):
        domain = AddressDomainService()
        address = domain.create(self.user, valid_address_payload(), actor=self.user)
        audit = AddressAuditLog.objects.filter(address=address, action="create").first()
        self.assertIsNotNone(audit)
        self.assertIn("verified_at", audit.changed_fields)
        self.assertIsInstance(audit.changed_fields["verified_at"], str)

    def test_incomplete_profile_returns_400_not_500(self):
        incomplete = User(
            id=uuid.uuid4(),
            phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
            country_code="+1",
            email=f"{uuid.uuid4().hex}@example.com",
            first_name="",
            last_name="Doe",
        )
        incomplete.set_password("testpass123")
        incomplete.save()

        client = APIClient()
        token = str(RefreshToken.for_user(incomplete).access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("profile", response.data)

    def test_missing_phone_returns_400_not_500(self):
        no_phone = User(
            id=uuid.uuid4(),
            phone_number=None,
            country_code="+1",
            email=f"{uuid.uuid4().hex}@example.com",
            first_name="Jane",
            last_name="Doe",
        )
        no_phone.set_password("testpass123")
        no_phone.save()

        client = APIClient()
        token = str(RefreshToken.for_user(no_phone).access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("profile", response.data)

    def test_invalid_user_phone_returns_400_not_500(self):
        bad_phone_user = make_user(
            phone_number="+1234",
            first_name="Jane",
            last_name="Doe",
            country_code="+1",
        )
        client = auth_client(bad_phone_user)
        response = client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("profile", response.data)
