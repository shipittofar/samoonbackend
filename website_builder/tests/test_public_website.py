"""Tests for public website read-only endpoint."""
import copy
import uuid

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Branch, Owner, Tenant
from website_builder.constants import DEFAULT_SECTIONS
from website_builder.models import BranchWebsiteOverride, WebsiteLayout, WebsiteLayoutStatus
from website_builder.tests.test_website_builder import FULL_LAYOUT_PAYLOAD, make_tenant_with_owner


PUBLIC_WEBSITE_URL = "/api/public/websites/{tenant_id}/"


def make_branch(tenant, **kwargs):
    defaults = {"name": f"Branch {uuid.uuid4().hex[:6]}"}
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


class PublicWebsiteAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant)
        self.url = PUBLIC_WEBSITE_URL.format(tenant_id=self.tenant.id)

    def test_unauthenticated_get_succeeds(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("layout", response.data)
        self.assertIn("theme", response.data)
        self.assertIn("branding", response.data)
        self.assertIn("image", response.data)
        self.assertIn("sections", response.data)
        self.assertIn("branchOverrides", response.data)

    def test_no_permission_required(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("permission_denied", str(response.data))

    def test_draft_layout_returns_defaults(self):
        WebsiteLayout.objects.create(
            tenant=self.tenant,
            layout_data=copy.deepcopy(FULL_LAYOUT_PAYLOAD),
            status=WebsiteLayoutStatus.DRAFT,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["sections"]), len(DEFAULT_SECTIONS))
        self.assertNotIn("customNestedField", response.data["layout"])

    def test_published_layout_returned(self):
        published_payload = copy.deepcopy(FULL_LAYOUT_PAYLOAD)
        published_payload["status"] = "published"
        layout = WebsiteLayout.objects.create(
            tenant=self.tenant,
            layout_data=published_payload,
            status=WebsiteLayoutStatus.PUBLISHED,
        )
        BranchWebsiteOverride.objects.create(
            website_layout=layout,
            branch=self.branch,
            override_data={"heroHeadline": "Branch headline"},
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["layout"]["hero"]["headline"], "Welcome")
        self.assertEqual(response.data["layout"]["brandTheme"], "modern")
        self.assertEqual(
            response.data["branchOverrides"][str(self.branch.id)]["heroHeadline"],
            "Branch headline",
        )
        self.assertIn("is_active", response.data)
        self.assertIn("status", response.data)
        self.assertIn("tenant", response.data)
        self.assertNotIn("lastSavedAt", response.data)

    def test_unknown_tenant_returns_404(self):
        response = self.client.get(
            PUBLIC_WEBSITE_URL.format(tenant_id=uuid.uuid4()),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_branding_exposed_and_layout_theme_unchanged(self):
        self.tenant.settings = {
            "theme": {
                "primaryColor": "#112233",
                "accentHoverColor": "#aabbcc",
                "fontBody": "inter",
                "fontsByLocale": {"en": "inter"},
            }
        }
        self.tenant.save(update_fields=["settings"])

        published_payload = copy.deepcopy(FULL_LAYOUT_PAYLOAD)
        published_payload["status"] = "published"
        WebsiteLayout.objects.create(
            tenant=self.tenant,
            layout_data=published_payload,
            status=WebsiteLayoutStatus.PUBLISHED,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["branding"]["primaryColor"], "#112233")
        self.assertEqual(response.data["branding"]["fontBody"], "inter")
        self.assertEqual(
            response.data["theme"],
            {"borderRadius": "xl", "cardStyle": "elevated"},
        )
        self.assertNotIn("primaryColor", response.data["theme"])
        self.assertNotIn("logo", response.data["branding"])
        layout = WebsiteLayout.objects.get(tenant=self.tenant)
        self.assertNotIn("primaryColor", layout.layout_data.get("theme", {}))

    def test_hidden_visible_tenant_returns_not_found(self):
        self.tenant.is_active = False
        self.tenant.save(update_fields=["is_active"])

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_status_tenant_returns_not_found(self):
        self.tenant.status = "inactive"
        self.tenant.save(update_fields=["status"])

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_closed_status_tenant_returns_not_found(self):
        self.tenant.status = "closed"
        self.tenant.save(update_fields=["status"])

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
