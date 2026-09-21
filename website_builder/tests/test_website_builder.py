"""API tests for Website Builder Phase 1 endpoints."""
import io
import copy
import tempfile
import uuid

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Branch, Owner, Tenant, TenantStatus
from website_builder.constants import DEFAULT_LAYOUT, DEFAULT_SECTIONS
from website_builder.models import BranchWebsiteOverride, WebsiteLayout


LAYOUT_URL = "/api/tenants/{tenant_id}/website/layout/"
OVERRIDES_URL = "/api/tenants/{tenant_id}/branches/{branch_id}/website/overrides/"
MEDIA_URL = "/api/tenants/{tenant_id}/website/media/"


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()

FULL_LAYOUT_PAYLOAD = {
    "sections": DEFAULT_SECTIONS,
    "hero": {"headline": "Welcome", "alignment": "center", "theme": "dark"},
    "about": {"story": "Our story"},
    "contact": {"email": "hello@example.com"},
    "faq": [{"id": "1", "question": "Q?", "answer": "A."}],
    "theme": {"borderRadius": "xl", "cardStyle": "elevated"},
    "status": "draft",
    "brandTheme": "modern",
    "heroConfig": {
        "layout": "hero_a",
        "backgroundType": "image",
        "alignment": "center",
        "primaryCta": "view_menu",
    },
    "sectionTemplates": {
        "gallery": "grid",
        "reviews": "cards",
        "contact": "map_left",
        "about": "story_left",
    },
    "navItems": [
        {"key": "menu", "enabled": True, "order": 0},
        {"key": "reviews", "enabled": True, "order": 1, "label": "Our Reviews"},
    ],
    "versions": [],
    "customNestedField": {"keepMe": True},
}

BRANCH_OVERRIDE_PAYLOAD = {
    "heroHeadline": "Branch headline",
    "heroSubheadline": "Branch sub",
    "heroImage": "https://cdn.example/hero.jpg",
    "description": "Branch description",
    "phone_number": "+1234567890",
    "gallery": ["https://cdn.example/1.jpg", "https://cdn.example/2.jpg"],
    "about": "Branch about text",
    "extraField": "preserved",
}


def make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": f"+1555{uuid.uuid4().int % 10**7:07d}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "first_name": "Test",
        "last_name": "User",
    }
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


def make_tenant_with_owner():
    user = make_user()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"Tenant {uuid.uuid4().hex[:6]}",
        status=TenantStatus.ACTIVE,
        is_active=True,
    )
    return user, tenant


def make_branch(tenant, **kwargs):
    defaults = {"name": f"Branch {uuid.uuid4().hex[:6]}"}
    defaults.update(kwargs)
    return Branch.objects.create(tenant=tenant, **defaults)


class WebsiteBuilderLayoutAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.other_user, self.other_tenant = make_tenant_with_owner()
        self.client.force_authenticate(user=self.owner_user)
        self.layout_url = LAYOUT_URL.format(tenant_id=self.tenant.id)

    def test_create_default_layout_on_first_get(self):
        self.assertFalse(WebsiteLayout.objects.filter(tenant=self.tenant).exists())

        response = self.client.get(self.layout_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(WebsiteLayout.objects.filter(tenant=self.tenant).exists())
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(len(response.data["sections"]), len(DEFAULT_SECTIONS))

    def test_get_returns_valid_homepage_layout_shape(self):
        response = self.client.get(self.layout_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for field in (
            "sections",
            "hero",
            "about",
            "contact",
            "faq",
            "theme",
            "status",
        ):
            self.assertIn(field, response.data)
        self.assertNotIn("data", response.data)

    def test_put_roundtrip_preserves_optional_fields(self):
        payload = copy.deepcopy(FULL_LAYOUT_PAYLOAD)
        response = self.client.put(self.layout_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["brandTheme"], "modern")
        self.assertEqual(response.data["heroConfig"]["layout"], "hero_a")
        self.assertEqual(response.data["sectionTemplates"]["gallery"], "grid")
        self.assertEqual(response.data["navItems"][1]["label"], "Our Reviews")
        self.assertEqual(response.data["customNestedField"]["keepMe"], True)

        get_response = self.client.get(self.layout_url)
        self.assertEqual(get_response.data["brandTheme"], "modern")
        self.assertEqual(get_response.data["heroConfig"]["layout"], "hero_a")
        self.assertEqual(get_response.data["sectionTemplates"]["gallery"], "grid")
        self.assertEqual(get_response.data["navItems"][1]["label"], "Our Reviews")
        self.assertEqual(get_response.data["customNestedField"]["keepMe"], True)

    def test_put_updates_last_saved_at(self):
        payload = copy.deepcopy(FULL_LAYOUT_PAYLOAD)
        response = self.client.put(self.layout_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("lastSavedAt", response.data)
        self.assertRegex(response.data["lastSavedAt"], r"^\d{4}-\d{2}-\d{2}T")

        layout = WebsiteLayout.objects.get(tenant=self.tenant)
        self.assertIsNotNone(layout.last_saved_at)

    def test_tenant_isolation(self):
        other_url = LAYOUT_URL.format(tenant_id=self.other_tenant.id)
        payload = copy.deepcopy(FULL_LAYOUT_PAYLOAD)
        payload["hero"]["headline"] = "Other tenant headline"

        denied = self.client.put(other_url, payload, format="json")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get(self.layout_url)

        self.assertNotEqual(response.data.get("hero", {}).get("headline"), "Other tenant headline")

    def test_no_payload_field_loss_in_database(self):
        payload = copy.deepcopy(FULL_LAYOUT_PAYLOAD)
        self.client.put(self.layout_url, payload, format="json")

        layout = WebsiteLayout.objects.get(tenant=self.tenant)
        self.assertEqual(layout.layout_data["customNestedField"]["keepMe"], True)
        self.assertEqual(layout.layout_data["navItems"][1]["label"], "Our Reviews")


class WebsiteBuilderBranchOverridesAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.branch = make_branch(self.tenant)
        self.other_branch = make_branch(self.tenant)
        self.other_user, self.other_tenant = make_tenant_with_owner()
        self.foreign_branch = make_branch(self.other_tenant)
        self.client.force_authenticate(user=self.owner_user)
        self.overrides_url = OVERRIDES_URL.format(
            tenant_id=self.tenant.id,
            branch_id=self.branch.id,
        )

    def test_branch_override_get_empty(self):
        response = self.client.get(self.overrides_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data, {})
        self.assertNotIn("data", response.data)

    def test_branch_override_put_roundtrip(self):
        payload = copy.deepcopy(BRANCH_OVERRIDE_PAYLOAD)
        put_response = self.client.put(self.overrides_url, payload, format="json")

        self.assertEqual(put_response.status_code, status.HTTP_200_OK, put_response.data)
        self.assertEqual(put_response.data["heroHeadline"], "Branch headline")
        self.assertEqual(put_response.data["extraField"], "preserved")

        get_response = self.client.get(self.overrides_url)
        self.assertEqual(get_response.data, put_response.data)
        self.assertTrue(
            BranchWebsiteOverride.objects.filter(
                website_layout__tenant=self.tenant,
                branch=self.branch,
            ).exists()
        )

    def test_branch_isolation(self):
        other_url = OVERRIDES_URL.format(
            tenant_id=self.tenant.id,
            branch_id=self.other_branch.id,
        )
        self.client.put(
            self.overrides_url,
            {"heroHeadline": "Branch A"},
            format="json",
        )
        response = self.client.get(other_url)

        self.assertEqual(response.data, {})

    def test_foreign_branch_returns_not_found(self):
        foreign_url = OVERRIDES_URL.format(
            tenant_id=self.tenant.id,
            branch_id=self.foreign_branch.id,
        )
        response = self.client.get(foreign_url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
    MEDIA_ROOT=tempfile.mkdtemp(),
)
class WebsiteBuilderMediaUploadAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_user, self.tenant = make_tenant_with_owner()
        self.client.force_authenticate(user=self.owner_user)
        self.media_url = MEDIA_URL.format(tenant_id=self.tenant.id)

    def test_media_upload_returns_url_only(self):
        upload = SimpleUploadedFile(
            "hero.png",
            _png_bytes(),
            content_type="image/png",
        )
        response = self.client.post(
            self.media_url,
            {"file": upload},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIn("url", response.data)
        self.assertTrue(response.data["url"])

    def test_default_layout_matches_frontend_defaults(self):
        from website_builder.constants.defaults import DEFAULT_HERO, DEFAULT_THEME

        self.assertEqual(DEFAULT_LAYOUT["sections"], DEFAULT_SECTIONS)
        self.assertEqual(DEFAULT_LAYOUT["hero"], DEFAULT_HERO)
        self.assertEqual(DEFAULT_LAYOUT["theme"], DEFAULT_THEME)
        self.assertEqual(DEFAULT_LAYOUT["status"], "draft")
