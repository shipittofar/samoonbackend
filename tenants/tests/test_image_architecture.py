"""Independent Tenant and Branch image fields — no fallback or collapsing."""
import io
import json
import uuid

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Branch, Owner, Tenant, TenantStatus


def _jpeg_bytes(color=(200, 100, 50), size=(8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG")
    return buffer.getvalue()


def _upload(name, color=(200, 100, 50)):
    return SimpleUploadedFile(name, _jpeg_bytes(color), content_type="image/jpeg")


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


def make_tenant_with_owner(**kwargs):
    user = make_user()
    owner = Owner.objects.create(user=user)
    defaults = {
        "owner": owner,
        "name": f"Tenant {uuid.uuid4().hex[:6]}",
        "status": TenantStatus.ACTIVE,
        "is_active": True,
        "settings": {
            "marketplace": {
                "tagline": "Keep me",
            }
        },
    }
    defaults.update(kwargs)
    tenant = Tenant.objects.create(**defaults)
    return user, tenant


class TenantImageArchitectureAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user, self.tenant = make_tenant_with_owner()
        self.tenant.image = _upload("logo.jpg", (10, 10, 10))
        self.tenant.discover_avatar = _upload("avatar.jpg", (20, 20, 20))
        self.tenant.discover_cover = _upload("cover.jpg", (30, 30, 30))
        self.tenant.hero_image = _upload("hero.jpg", (40, 40, 40))
        self.tenant.save()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        cache.clear()

    def _update(self, payload):
        data = {
            "name": self.tenant.name,
            "status": self.tenant.status,
            "tax_percentage": str(self.tenant.tax_percentage),
            "settings": json.dumps(self.tenant.settings),
        }
        data.update(payload)
        return self.client.put(
            f"/api/tenants/{self.tenant.id}/update/",
            data=data,
            format="multipart",
        )

    def test_get_returns_independent_tenant_images(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(f"/api/tenants/{self.tenant.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["image"])
        self.assertTrue(data["discoverAvatar"])
        self.assertTrue(data["discoverCover"])
        self.assertTrue(data["heroImage"])
        self.assertNotEqual(data["image"], data["discoverAvatar"])
        self.assertNotEqual(data["image"], data["discoverCover"])
        self.assertNotEqual(data["discoverAvatar"], data["discoverCover"])
        self.assertNotEqual(data["heroImage"], data["image"])
        self.assertNotEqual(data["heroImage"], data["discoverAvatar"])
        self.assertNotEqual(data["heroImage"], data["discoverCover"])
        self.assertNotIn("heroImage", data["settings"].get("marketplace", {}))

    def test_update_discover_avatar_does_not_modify_logo(self):
        logo_name = self.tenant.image.name
        cover_name = self.tenant.discover_cover.name
        hero_name = self.tenant.hero_image.name

        response = self._update({"discoverAvatar": _upload("avatar2.jpg", (40, 40, 40))})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.image.name, logo_name)
        self.assertEqual(self.tenant.discover_cover.name, cover_name)
        self.assertEqual(self.tenant.hero_image.name, hero_name)
        self.assertNotEqual(self.tenant.discover_avatar.name, logo_name)

    def test_update_discover_cover_does_not_modify_logo_or_hero(self):
        logo_name = self.tenant.image.name
        avatar_name = self.tenant.discover_avatar.name
        hero_name = self.tenant.hero_image.name

        response = self._update({"discoverCover": _upload("cover2.jpg", (50, 50, 50))})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.image.name, logo_name)
        self.assertEqual(self.tenant.discover_avatar.name, avatar_name)
        self.assertEqual(self.tenant.hero_image.name, hero_name)

    def test_update_hero_does_not_modify_logo_or_discover_images(self):
        logo_name = self.tenant.image.name
        avatar_name = self.tenant.discover_avatar.name
        cover_name = self.tenant.discover_cover.name

        response = self._update({"heroImage": _upload("hero2.jpg", (60, 60, 60))})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.image.name, logo_name)
        self.assertEqual(self.tenant.discover_avatar.name, avatar_name)
        self.assertEqual(self.tenant.discover_cover.name, cover_name)
        self.assertTrue(self.tenant.hero_image)
        self.assertNotIn("heroImage", (self.tenant.settings or {}).get("marketplace", {}))
        self.assertTrue(response.data["heroImage"])
        self.assertNotIn("heroImage", response.data["settings"].get("marketplace", {}))

    def test_missing_tenant_images_stay_null_without_fallback(self):
        blank = Tenant.objects.create(
            owner=self.tenant.owner,
            name=f"Blank {uuid.uuid4().hex[:6]}",
            status=TenantStatus.ACTIVE,
            is_active=True,
            settings={"marketplace": {"tagline": "no hero"}},
        )
        Branch.objects.create(
            tenant=blank,
            name="Only Branch",
            is_default=True,
            marketplace_visible=True,
            image=_upload("branch-logo.jpg", (1, 1, 1)),
            cover_image=_upload("branch-cover.jpg", (2, 2, 2)),
            hero_image=_upload("branch-hero.jpg", (3, 3, 3)),
        )
        cache.clear()
        self.client.force_authenticate(user=None)
        data = self.client.get(f"/api/tenants/{blank.id}/").json()
        self.assertIsNone(data["image"])
        self.assertIsNone(data["discoverAvatar"])
        self.assertIsNone(data["discoverCover"])
        self.assertIsNone(data["heroImage"])
        self.assertNotIn("heroImage", data["settings"].get("marketplace", {}))

        discover = self.client.get("/api/public/discover/").json()["results"]
        item = next(row for row in discover if row["id"] == str(blank.id))
        self.assertIsNone(item["image"])
        self.assertIsNone(item["discoverAvatar"])
        self.assertIsNone(item["discoverCover"])
        self.assertIsNone(item["heroImage"])
        self.assertNotIn("heroImage", item["marketplace"])
        self.assertNotIn("coverImage", item["marketplace"])
        self.assertIsNone(item["image"])
        self.assertNotEqual(item["heroImage"], item["branches"][0]["heroImage"])

    def test_existing_logo_does_not_fill_missing_discover_avatar(self):
        """Header keeps logo/text fallback when discoverAvatar is unset."""
        tenant = Tenant.objects.create(
            owner=self.tenant.owner,
            name=f"Logo Only {uuid.uuid4().hex[:6]}",
            status=TenantStatus.ACTIVE,
            is_active=True,
            image=_upload("existing-logo.jpg", (80, 80, 80)),
            settings={
                "marketplace": {
                    "tagline": "logo text fallback",
                }
            },
        )
        Branch.objects.create(
            tenant=tenant,
            name="Has Media",
            is_default=True,
            marketplace_visible=True,
            image=_upload("branch-only-logo.jpg", (1, 1, 1)),
            cover_image=_upload("branch-only-cover.jpg", (2, 2, 2)),
        )
        cache.clear()
        self.client.force_authenticate(user=None)

        data = self.client.get(f"/api/tenants/{tenant.id}/").json()
        self.assertTrue(data["image"])
        self.assertIsNone(data["discoverAvatar"])
        self.assertIsNone(data["discoverCover"])
        self.assertIsNone(data["heroImage"])
        self.assertNotIn("heroImage", data["settings"].get("marketplace", {}))

        discover = self.client.get("/api/public/discover/").json()["results"]
        item = next(row for row in discover if row["id"] == str(tenant.id))
        self.assertTrue(item["image"])
        self.assertIsNone(item["discoverAvatar"])
        self.assertIsNone(item["discoverCover"])
        self.assertNotEqual(item["discoverAvatar"], item["branches"][0]["coverImage"])
        self.assertNotEqual(item["discoverAvatar"], item["branches"][0]["image"])

    def test_create_accepts_independent_discover_fields(self):
        response = self.client.post(
            "/api/tenants/create/",
            data={
                "name": f"New Images {uuid.uuid4().hex[:6]}",
                "image": _upload("new-logo.jpg", (11, 11, 11)),
                "discoverAvatar": _upload("new-avatar.jpg", (22, 22, 22)),
                "discoverCover": _upload("new-cover.jpg", (33, 33, 33)),
                "heroImage": _upload("new-hero.jpg", (44, 44, 44)),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["image"])
        self.assertTrue(response.data["discoverAvatar"])
        self.assertTrue(response.data["discoverCover"])
        self.assertTrue(response.data["heroImage"])
        self.assertNotEqual(response.data["image"], response.data["discoverAvatar"])
        self.assertNotEqual(response.data["heroImage"], response.data["image"])
        self.assertNotIn("heroImage", response.data["settings"].get("marketplace", {}))

    def test_hero_is_independent_from_stale_marketplace_hero_image(self):
        Tenant.objects.filter(pk=self.tenant.pk).update(
            settings={
                "marketplace": {
                    "tagline": "Keep me",
                    "heroImage": "https://cdn.example/stale-settings-hero.jpg",
                }
            }
        )
        cache.clear()
        self.client.force_authenticate(user=None)
        data = self.client.get(f"/api/tenants/{self.tenant.id}/").json()
        self.assertTrue(data["heroImage"])
        self.assertNotEqual(
            data["heroImage"],
            "https://cdn.example/stale-settings-hero.jpg",
        )
        self.assertNotIn("heroImage", data["settings"].get("marketplace", {}))
        discover = self.client.get("/api/public/discover/").json()["results"]
        item = next(row for row in discover if row["id"] == str(self.tenant.id))
        self.assertEqual(item["heroImage"], data["heroImage"])
        self.assertNotIn("heroImage", item["marketplace"])


class BranchImageArchitectureAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user, self.tenant = make_tenant_with_owner()
        self.branch = Branch.objects.create(
            tenant=self.tenant,
            name="Main",
            image=_upload("branch-logo.jpg", (1, 2, 3)),
            cover_image=_upload("branch-cover.jpg", (4, 5, 6)),
            hero_image=_upload("branch-hero.jpg", (7, 8, 9)),
        )
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        cache.clear()

    def test_get_returns_independent_branch_images_without_avatar(self):
        response = self.client.get(
            f"/api/tenants/{self.tenant.id}/branches/{self.branch.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["image"])
        self.assertTrue(data["coverImage"])
        self.assertTrue(data["heroImage"])
        self.assertNotEqual(data["image"], data["coverImage"])
        self.assertNotEqual(data["coverImage"], data["heroImage"])
        self.assertNotEqual(data["image"], data["heroImage"])
        self.assertNotIn("avatar", data)

    def test_missing_branch_images_stay_null_without_fallback(self):
        empty = Branch.objects.create(tenant=self.tenant, name="Empty Media")
        data = self.client.get(
            f"/api/tenants/{self.tenant.id}/branches/{empty.id}/"
        ).json()
        self.assertIsNone(data["image"])
        self.assertIsNone(data["coverImage"])
        self.assertIsNone(data["heroImage"])
        self.assertNotIn("avatar", data)


class TenantBranchImageIsolationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user, self.tenant = make_tenant_with_owner()
        self.tenant.image = _upload("tenant-logo.jpg", (9, 9, 9))
        self.tenant.discover_avatar = _upload("tenant-avatar.jpg", (8, 8, 8))
        self.tenant.discover_cover = _upload("tenant-cover.jpg", (7, 7, 7))
        self.tenant.hero_image = _upload("tenant-hero.jpg", (6, 6, 6))
        self.tenant.save()
        self.alpha = Branch.objects.create(
            tenant=self.tenant,
            name="Alpha",
            slug="alpha-iso",
            is_default=False,
            marketplace_visible=True,
            image=_upload("alpha-logo.jpg", (1, 0, 0)),
            cover_image=_upload("alpha-cover.jpg", (0, 1, 0)),
            hero_image=_upload("alpha-hero.jpg", (0, 0, 1)),
        )
        self.beta = Branch.objects.create(
            tenant=self.tenant,
            name="Beta",
            slug="beta-iso",
            is_default=True,
            marketplace_visible=True,
            image=_upload("beta-logo.jpg", (2, 0, 0)),
            cover_image=_upload("beta-cover.jpg", (0, 2, 0)),
            hero_image=_upload("beta-hero.jpg", (0, 0, 2)),
        )
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _tenant_images(self):
        self.tenant.refresh_from_db()
        return (
            self.tenant.image.name,
            self.tenant.discover_avatar.name,
            self.tenant.discover_cover.name,
            self.tenant.hero_image.name,
        )

    def test_changing_default_branch_does_not_change_tenant_images(self):
        before = self._tenant_images()
        self.alpha.is_default = True
        self.alpha.save(update_fields=["is_default"])
        self.beta.is_default = False
        self.beta.save(update_fields=["is_default"])
        cache.clear()

        self.assertEqual(self._tenant_images(), before)
        public = self.client.get(f"/api/tenants/{self.tenant.id}/").json()
        discover = self.client.get("/api/public/discover/").json()["results"][0]
        self.assertEqual(discover["image"], public["image"])
        self.assertEqual(discover["discoverAvatar"], public["discoverAvatar"])
        self.assertEqual(discover["discoverCover"], public["discoverCover"])
        self.assertEqual(discover["heroImage"], public["heroImage"])
        self.assertTrue(public["heroImage"])
        self.assertNotIn("heroImage", public["settings"].get("marketplace", {}))
        self.assertNotIn("heroImage", discover["marketplace"])
        self.assertEqual(discover["marketplace"]["primaryBranchSlug"], self.alpha.slug)
        self.assertNotIn("coverImage", discover["marketplace"])
        branch_covers = {row["coverImage"] for row in discover["branches"]}
        self.assertNotIn(discover["discoverCover"], branch_covers)
        self.assertNotIn(discover["discoverAvatar"], branch_covers)
        self.assertTrue(public["discoverAvatar"])
        self.assertNotEqual(public["discoverAvatar"], public["image"])
