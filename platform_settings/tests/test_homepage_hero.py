import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from access.tests.helpers import make_tenant, make_user
from platform_settings.models import PlatformSetting
from uploads.models import UploadAsset
from uploads.services.upload_bll import expire_unattached_assets
from uploads.state import UploadAssetStatus

URL = "/api/platform/homepage/hero/"


def hero_asset(user, *, status=UploadAssetStatus.READY, entity=("platform", "homepage"), tenant=None, expired=False):
    return UploadAsset.objects.create(
        created_by=user,
        tenant=tenant,
        purpose="website_media",
        entity_type=entity[0],
        entity_id=entity[1],
        original_filename="hero.webp",
        mime_type="image/webp",
        byte_size=10,
        storage_key=f"platform/homepage/{uuid.uuid4()}/original",
        status=status,
        expires_at=timezone.now() + (timedelta(hours=-1) if expired else timedelta(hours=24)),
    )


class HomepageHeroApiTests(TestCase):
    def setUp(self):
        self.root = make_user(is_superuser=True, is_staff=True)
        self.client = APIClient()

    def put(self, body, user=None):
        self.client.force_authenticate(user or self.root)
        return self.client.put(URL, body, format="json")

    def test_get_is_404_until_saved_then_public(self):
        anon = APIClient()
        self.assertEqual(anon.get(URL).status_code, 404)
        res = self.put({"backgroundImages": [{"id": "a", "src": "https://cdn.example.com/a.jpg"}]})
        self.assertEqual(res.status_code, 200, res.content)
        got = anon.get(URL)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["backgroundImages"][0]["src"], "https://cdn.example.com/a.jpg")

    def test_public_get_ignores_a_bad_token(self):
        self.put({"backgroundImages": []})
        anon = APIClient()
        anon.credentials(HTTP_AUTHORIZATION="Bearer expired.token.value")
        self.assertEqual(anon.get(URL).status_code, 200)

    def test_only_superusers_can_save(self):
        owner, _ = make_tenant()
        self.assertEqual(self.put({"backgroundImages": []}, user=owner).status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.put(URL, {"backgroundImages": []}, format="json").status_code, (401, 403))
        self.assertFalse(PlatformSetting.objects.exists())

    def test_normalizes_like_the_frontend(self):
        res = self.put({
            "backgroundImages": [
                {"src": "  "},
                {"id": "b", "src": "/media/b.jpg", "enabled": False, "objectPosition": "top", "objectPositionMobile": "nope", "altText": "Dinner"},
            ],
            "slideshowIntervalMs": 10,
            "slideshowTransitionMs": 999999,
        })
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["slideshowIntervalMs"], 2000)
        self.assertEqual(body["slideshowTransitionMs"], 3000)
        self.assertEqual(body["backgroundImages"], [
            {"id": "b", "src": "/media/b.jpg", "order": 0, "enabled": False, "altText": "Dinner", "objectPosition": "top"},
        ])

    def test_rejects_data_urls_and_too_many_images(self):
        self.assertEqual(self.put({"backgroundImages": [{"src": "data:image/png;base64,AAA"}]}).status_code, 400)
        self.assertEqual(self.put({"backgroundImages": [{"src": "javascript:alert(1)"}]}).status_code, 400)
        many = [{"src": f"https://x/{i}.jpg"} for i in range(13)]
        self.assertEqual(self.put({"backgroundImages": many}).status_code, 400)

    def test_uploaded_image_is_attached_and_survives_cleanup(self):
        asset = hero_asset(self.root)
        res = self.put({"backgroundImages": [{"id": "u", "src": "blob-preview-ignored", "assetId": str(asset.id)}]})
        self.assertEqual(res.status_code, 200, res.content)
        asset.refresh_from_db()
        self.assertEqual(asset.status, UploadAssetStatus.ATTACHED)
        self.assertEqual(res.json()["backgroundImages"][0]["assetId"], str(asset.id))
        # Past its expiry, an attached hero image is not cleaned up.
        UploadAsset.objects.filter(id=asset.id).update(expires_at=timezone.now() - timedelta(hours=1))
        expire_unattached_assets()
        asset.refresh_from_db()
        self.assertEqual(asset.status, UploadAssetStatus.ATTACHED)

    def test_removed_image_is_released(self):
        asset = hero_asset(self.root)
        self.put({"backgroundImages": [{"assetId": str(asset.id)}]})
        self.put({"backgroundImages": [{"src": "https://cdn.example.com/new.jpg"}]})
        asset.refresh_from_db()
        self.assertEqual(asset.status, UploadAssetStatus.DETACHED)

    def test_rejects_uploads_that_are_not_platform_hero_images(self):
        owner, tenant = make_tenant()
        tenant_asset = hero_asset(owner, entity=("", ""), tenant=tenant)
        self.assertEqual(self.put({"backgroundImages": [{"assetId": str(tenant_asset.id)}]}).status_code, 400)
        processing = hero_asset(self.root, status=UploadAssetStatus.PROCESSING)
        self.assertEqual(self.put({"backgroundImages": [{"assetId": str(processing.id)}]}).status_code, 400)
        expired = hero_asset(self.root, expired=True)
        self.assertEqual(self.put({"backgroundImages": [{"assetId": str(expired.id)}]}).status_code, 400)
        self.assertEqual(self.put({"backgroundImages": [{"assetId": "not-a-uuid"}]}).status_code, 400)
        tenant_asset.refresh_from_db()
        self.assertEqual(tenant_asset.status, UploadAssetStatus.READY)
