"""Unit tests for tenant visibility vs operational availability helpers."""
from django.test import SimpleTestCase

from tenants.models import TenantStatus
from tenants.selectors.tenant_availability import (
    PUBLIC_TENANT_FILTER,
    PUBLIC_TENANT_LOOKUP,
    OPERATIONAL_TENANT_LOOKUP,
    tenant_is_operationally_available,
    tenant_is_publicly_listable,
    tenant_is_publicly_visible,
)


class _TenantStub:
    def __init__(self, *, is_active: bool, status: str):
        self.is_active = is_active
        self.status = status


class TenantAvailabilityHelperTests(SimpleTestCase):
    def test_publicly_visible_checks_is_active_only(self):
        tenant = _TenantStub(is_active=True, status=TenantStatus.INACTIVE)
        self.assertTrue(tenant_is_publicly_visible(tenant))

    def test_operationally_available_requires_active_status(self):
        visible_inactive = _TenantStub(is_active=True, status=TenantStatus.INACTIVE)
        self.assertFalse(tenant_is_operationally_available(visible_inactive))

        operational = _TenantStub(is_active=True, status=TenantStatus.ACTIVE)
        self.assertTrue(tenant_is_operationally_available(operational))

    def test_hidden_tenant_is_not_visible_or_operational(self):
        tenant = _TenantStub(is_active=False, status=TenantStatus.ACTIVE)
        self.assertFalse(tenant_is_publicly_visible(tenant))
        self.assertFalse(tenant_is_operationally_available(tenant))
        self.assertFalse(tenant_is_publicly_listable(tenant))

    def test_public_catalog_lookups_require_both_dimensions(self):
        self.assertEqual(PUBLIC_TENANT_LOOKUP, OPERATIONAL_TENANT_LOOKUP)
        self.assertEqual(
            PUBLIC_TENANT_FILTER,
            {"is_active": True, "status": TenantStatus.ACTIVE},
        )
