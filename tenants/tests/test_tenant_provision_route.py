"""Tenant provision URL resolves to the canonical create handler."""
from django.test import SimpleTestCase
from django.urls import resolve, reverse

from tenants.api.views.tenant import TenantCreateAPIView


class TenantProvisionRouteTests(SimpleTestCase):
    def test_provision_path_resolves_to_tenant_create_view(self):
        match = resolve("/api/tenants/provision/")
        self.assertEqual(match.func.view_class, TenantCreateAPIView)
        self.assertEqual(match.url_name, "tenant-provision")

    def test_create_path_resolves_to_tenant_create_view(self):
        match = resolve("/api/tenants/create/")
        self.assertEqual(match.func.view_class, TenantCreateAPIView)
        self.assertEqual(match.url_name, "tenant-create")

    def test_provision_reverse_name(self):
        self.assertEqual(reverse("tenants:tenant-provision"), "/api/tenants/provision/")
