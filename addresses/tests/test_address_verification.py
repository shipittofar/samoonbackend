"""Tests for automatic address verification on create and migration backfill."""

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from addresses.domain.verification import VerificationStatus
from addresses.models import Address
from addresses.services.address_domain_service import (
    SYSTEM_VERIFICATION_SOURCE,
    AddressDomainService,
)
from addresses.tests.test_addresses import auth_client, make_user, valid_address_payload


class AutoVerificationOnCreateTests(TestCase):
    def setUp(self):
        self.user = make_user(phone_number="+15559123456")
        self.domain = AddressDomainService()

    def test_new_address_is_automatically_verified(self):
        address = self.domain.create(self.user, valid_address_payload())
        self.assertEqual(address.verification_status, VerificationStatus.VERIFIED)
        self.assertTrue(address.is_verified)
        self.assertIsNotNone(address.verified_at)
        self.assertEqual(address.verification_source, SYSTEM_VERIFICATION_SOURCE)

    def test_api_create_returns_verified_address(self):
        client = auth_client(self.user)
        response = client.post(
            "/api/users/addresses/",
            valid_address_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["verification_status"], VerificationStatus.VERIFIED)
        self.assertTrue(response.data["is_verified"])
        self.assertIsNotNone(response.data["verified_at"])
        self.assertEqual(response.data["verification_source"], SYSTEM_VERIFICATION_SOURCE)


class VerifyExistingAddressesMigrationTests(TestCase):
    def test_migration_verifies_existing_unverified_addresses(self):
        import importlib

        user = make_user(phone_number="+15559123456")
        address = Address.objects.create(
            user=user,
            title="Home",
            address_type="home",
            first_name="Jane",
            last_name="Doe",
            phone="5559123456",
            country_code="+1",
            country="US",
            city="Los Angeles",
            street="100 Legacy St",
            postal_code="90001",
            fingerprint=uuid.uuid4().hex,
            verification_status=VerificationStatus.PENDING,
            is_verified=False,
            verified_at=None,
            verification_source="",
        )
        created_at = address.created_at

        migration = importlib.import_module(
            "addresses.migrations.0004_verify_existing_addresses"
        )
        from django.apps import apps as django_apps

        migration.verify_existing_addresses(django_apps, None)

        address.refresh_from_db()
        self.assertEqual(address.verification_status, VerificationStatus.VERIFIED)
        self.assertTrue(address.is_verified)
        self.assertEqual(address.verified_at, created_at)
        self.assertEqual(address.verification_source, SYSTEM_VERIFICATION_SOURCE)
