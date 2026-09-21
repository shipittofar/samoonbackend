from datetime import timedelta
import io
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from menu.models import MenuCategory, MenuItem
from tenants.models import Branch, Owner, Tenant, TenantStatus
from uploads.models import UploadAsset
from uploads.object_store import save_bytes
from uploads.services.upload_bll import expire_unattached_assets
from uploads.state import UploadAssetStatus


def _png(size=(32, 32), color=(12, 34, 56)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _upload_file(name="pic.png", size=(32, 32)):
    return SimpleUploadedFile(name, _png(size), content_type="image/png")


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


def make_tenant():
    user = make_user()
    owner = Owner.objects.create(user=user)
    tenant = Tenant.objects.create(
        owner=owner,
        name=f"T {uuid.uuid4().hex[:6]}",
        status=TenantStatus.ACTIVE,
        is_active=True,
    )
    branch = Branch.objects.create(tenant=tenant, name="Main")
    return user, tenant, branch


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class UploadApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user, self.tenant, self.branch = make_tenant()
        self.other, self.other_tenant, self.other_branch = make_tenant()
        self.client.force_authenticate(user=self.user)

    def _initiate(self, **overrides):
        payload = {
            "purpose": "tenant_logo",
            "filename": "logo.png",
            "mime_type": "image/png",
            "byte_size": len(_png()),
            "tenant_id": str(self.tenant.id),
        }
        payload.update(overrides)
        return self.client.post("/api/uploads/initiate/", payload, format="json")

    def _put_object(self, asset, content=None):
        save_bytes(asset.storage_key, SimpleUploadedFile("x.png", content or _png()))

    def test_initiate_valid(self):
        response = self._initiate()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["status"], UploadAssetStatus.INITIATED)
        self.assertEqual(response.data["upload"]["method"], "PUT")
        self.assertIn("Content-Type", response.data["upload"]["headers"])

    def test_initiate_invalid_mime(self):
        response = self._initiate(mime_type="application/pdf")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_initiate_invalid_size(self):
        response = self._initiate(byte_size=99 * 1024 * 1024)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_initiate_unknown_purpose(self):
        response = self._initiate(purpose="not_a_purpose")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cross_tenant_initiate_denied(self):
        response = self._initiate(tenant_id=str(self.other_tenant.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_initiate_idempotency(self):
        first = self._initiate(idempotency_key="abc")
        second = self._initiate(idempotency_key="abc")
        self.assertEqual(first.data["asset_id"], second.data["asset_id"])

    def test_complete_missing_object(self):
        asset_id = self._initiate().data["asset_id"]
        response = self.client.post(f"/api/uploads/{asset_id}/complete/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_valid_and_idempotent(self):
        asset_id = self._initiate().data["asset_id"]
        asset = UploadAsset.objects.get(pk=asset_id)
        self._put_object(asset)
        first = self.client.post(f"/api/uploads/{asset_id}/complete/")
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        self.assertEqual(first.data["status"], UploadAssetStatus.READY)
        self.assertIn("optimized", first.data["variants"])
        second = self.client.post(f"/api/uploads/{asset_id}/complete/")
        self.assertEqual(second.data["status"], UploadAssetStatus.READY)

    def test_complete_size_mismatch(self):
        payload_size = len(_png((8, 8)))
        response = self._initiate(byte_size=payload_size)
        asset = UploadAsset.objects.get(pk=response.data["asset_id"])
        self._put_object(asset, _png((64, 64)))
        complete = self.client.post(f"/api/uploads/{asset.id}/complete/")
        self.assertEqual(complete.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_invalid_image(self):
        blob = b"notanimage"
        response = self._initiate(byte_size=len(blob))
        asset = UploadAsset.objects.get(pk=response.data["asset_id"])
        self._put_object(asset, b"notanimage")
        complete = self.client.post(f"/api/uploads/{asset.id}/complete/")
        self.assertEqual(complete.status_code, status.HTTP_400_BAD_REQUEST)

    def test_status_and_cancel(self):
        asset_id = self._initiate().data["asset_id"]
        detail = self.client.get(f"/api/uploads/{asset_id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        cancel = self.client.post(f"/api/uploads/{asset_id}/cancel/")
        self.assertEqual(cancel.data["status"], UploadAssetStatus.EXPIRED)

    def test_attach_wrong_purpose(self):
        asset_id = self._initiate().data["asset_id"]
        asset = UploadAsset.objects.get(pk=asset_id)
        self._put_object(asset)
        self.client.post(f"/api/uploads/{asset_id}/complete/")
        self.client.patch(
            f"/api/tenants/{self.tenant.id}/update/",
            {"name": self.tenant.name, "status": self.tenant.status, "image_asset_id": asset_id},
            format="json",
        )
        # tenant update serializer requires name/status; purpose tenant_logo is correct
        # now try attach as avatar
        avatar = self.client.patch(
            "/api/auth/profile/avatar/",
            {"avatar_asset_id": asset_id},
            format="json",
        )
        self.assertEqual(avatar.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tenant_attach_and_replace(self):
        first_id = self._initiate().data["asset_id"]
        first = UploadAsset.objects.get(pk=first_id)
        self._put_object(first)
        self.client.post(f"/api/uploads/{first_id}/complete/")
        attach = self.client.patch(
            f"/api/tenants/{self.tenant.id}/update/",
            {
                "name": self.tenant.name,
                "status": self.tenant.status,
                "image_asset_id": first_id,
            },
            format="json",
        )
        self.assertEqual(attach.status_code, status.HTTP_200_OK, attach.data)
        first.refresh_from_db()
        self.assertEqual(first.status, UploadAssetStatus.ATTACHED)

        second_blob = _png((40, 40), (1, 2, 3))
        second_id = self._initiate(byte_size=len(second_blob)).data["asset_id"]
        second_asset = UploadAsset.objects.get(pk=second_id)
        self._put_object(second_asset, second_blob)
        complete_second = self.client.post(f"/api/uploads/{second_id}/complete/")
        self.assertEqual(complete_second.status_code, status.HTTP_200_OK, complete_second.data)
        second = self.client.patch(
            f"/api/tenants/{self.tenant.id}/update/",
            {
                "name": self.tenant.name,
                "status": self.tenant.status,
                "image_asset_id": second_id,
            },
            format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        first.refresh_from_db()
        second_asset.refresh_from_db()
        self.assertEqual(first.status, UploadAssetStatus.DETACHED)
        self.assertEqual(second_asset.status, UploadAssetStatus.ATTACHED)

    def test_orphan_cleanup_preserves_attached(self):
        ready_id = self._initiate().data["asset_id"]
        asset = UploadAsset.objects.get(pk=ready_id)
        self._put_object(asset)
        self.client.post(f"/api/uploads/{ready_id}/complete/")
        self.client.patch(
            f"/api/tenants/{self.tenant.id}/update/",
            {
                "name": self.tenant.name,
                "status": self.tenant.status,
                "image_asset_id": ready_id,
            },
            format="json",
        )
        orphan_id = self._initiate().data["asset_id"]
        orphan = UploadAsset.objects.get(pk=orphan_id)
        orphan.expires_at = timezone.now() - timedelta(hours=1)
        orphan.save(update_fields=["expires_at"])
        attached = UploadAsset.objects.get(pk=ready_id)
        attached.expires_at = timezone.now() - timedelta(hours=1)
        attached.save(update_fields=["expires_at"])
        expire_unattached_assets()
        orphan.refresh_from_db()
        attached.refresh_from_db()
        self.assertEqual(orphan.status, UploadAssetStatus.EXPIRED)
        self.assertEqual(attached.status, UploadAssetStatus.ATTACHED)

    def test_website_rejects_data_url(self):
        payload = {
            "sections": [],
            "hero": {"heroImage": "data:image/png;base64,abc"},
            "about": {},
            "contact": {},
            "faq": [],
            "theme": {},
            "status": "draft",
        }
        response = self.client.put(
            f"/api/tenants/{self.tenant.id}/website/layout/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_website_unsafe_file_rejected(self):
        response = self.client.post(
            f"/api/tenants/{self.tenant.id}/website/media/",
            {"file": SimpleUploadedFile("x.html", b"<script>", content_type="text/html")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_conflict_file_and_asset_id(self):
        asset_id = self._initiate().data["asset_id"]
        asset = UploadAsset.objects.get(pk=asset_id)
        self._put_object(asset)
        self.client.post(f"/api/uploads/{asset_id}/complete/")
        response = self.client.patch(
            "/api/auth/profile/avatar/",
            {"avatar": _upload_file(), "avatar_asset_id": asset_id},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class MenuMutationAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user, self.tenant, self.branch = make_tenant()
        self.category = MenuCategory.objects.create(
            branch=self.branch, name="Food"
        )

    def test_anonymous_item_create_denied(self):
        response = self.client.post(
            "/api/menu/create-items/",
            {
                "branch_id": str(self.branch.id),
                "category_id": str(self.category.id),
                "name": "Burger",
                "price": "9.99",
                "image": _upload_file(),
            },
            format="multipart",
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_anonymous_category_create_denied(self):
        response = self.client.post(
            "/api/menu/categories/",
            {
                "branch_id": str(self.branch.id),
                "name": "Drinks",
                "image": _upload_file(),
            },
            format="multipart",
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_owner_can_create_item(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/menu/create-items/",
            {
                "branch_id": str(self.branch.id),
                "category_id": str(self.category.id),
                "name": "Burger",
                "price": "9.99",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(MenuItem.objects.filter(name="Burger").exists())


class UploadProcessingAndStateTests(TestCase):
    def setUp(self):
        self.user, self.tenant, self.branch = make_tenant()

    def test_large_webp_is_dimension_limited(self):
        from django.core.files.base import ContentFile
        from uploads.processing import process_asset_image

        buf = io.BytesIO()
        Image.new("RGB", (2400, 1800), (9, 8, 7)).save(buf, format="WEBP", quality=90)
        blob = buf.getvalue()
        asset = UploadAsset.objects.create(
            created_by=self.user,
            tenant=self.tenant,
            purpose="tenant_logo",
            original_filename="big.webp",
            mime_type="image/webp",
            byte_size=len(blob),
            storage_key=f"tenants/{self.tenant.id}/assets/{uuid.uuid4()}/original",
            status=UploadAssetStatus.UPLOADED,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        save_bytes(asset.storage_key, ContentFile(blob))
        variants = process_asset_image(asset, max_dimension=1600)
        from django.core.files.storage import default_storage

        with default_storage.open(variants["optimized"], "rb") as fh:
            with Image.open(fh) as img:
                self.assertLessEqual(max(img.size), 1600)


    def test_state_machine_rejects_attached_to_ready(self):
        from uploads.state import can_transition

        self.assertTrue(can_transition(UploadAssetStatus.INITIATED, UploadAssetStatus.UPLOADED))
        self.assertFalse(can_transition(UploadAssetStatus.ATTACHED, UploadAssetStatus.READY))
        self.assertFalse(can_transition(UploadAssetStatus.EXPIRED, UploadAssetStatus.READY))

    def test_cross_tenant_attach_denied(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        payload = {
            "purpose": "tenant_logo",
            "filename": "logo.png",
            "mime_type": "image/png",
            "byte_size": len(_png()),
            "tenant_id": str(self.tenant.id),
        }
        asset_id = client.post("/api/uploads/initiate/", payload, format="json").data["asset_id"]
        asset = UploadAsset.objects.get(pk=asset_id)
        save_bytes(asset.storage_key, SimpleUploadedFile("x.png", _png()))
        client.post(f"/api/uploads/{asset_id}/complete/")
        other_user, other_tenant, _ = make_tenant()
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        response = other_client.patch(
            f"/api/tenants/{other_tenant.id}/update/",
            {
                "name": other_tenant.name,
                "status": other_tenant.status,
                "image_asset_id": asset_id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class UploadHardeningTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user, self.tenant, self.branch = make_tenant()
        self.other, self.other_tenant, self.other_branch = make_tenant()
        self.client.force_authenticate(user=self.user)

    def _initiate(self, **overrides):
        payload = {
            "purpose": "tenant_logo",
            "filename": "logo.png",
            "mime_type": "image/png",
            "byte_size": len(_png()),
            "tenant_id": str(self.tenant.id),
        }
        payload.update(overrides)
        return self.client.post("/api/uploads/initiate/", payload, format="json")

    def _put(self, asset, content=None):
        save_bytes(asset.storage_key, SimpleUploadedFile("x.png", content or _png()))

    def test_unauthenticated_initiate_denied(self):
        self.client.force_authenticate(user=None)
        response = self._initiate()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cross_tenant_get_complete_cancel_denied(self):
        asset_id = self._initiate().data["asset_id"]
        other = APIClient()
        other.force_authenticate(user=self.other)
        self.assertEqual(other.get(f"/api/uploads/{asset_id}/").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            other.post(f"/api/uploads/{asset_id}/complete/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            other.post(f"/api/uploads/{asset_id}/cancel/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_complete_ignores_uploaded_flag_and_requires_object(self):
        asset_id = self._initiate().data["asset_id"]
        response = self.client.post(
            f"/api/uploads/{asset_id}/complete/",
            {"uploaded": True, "storage_key": "tenants/other/assets/x/original"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_idempotent_initiate_does_not_reissue_after_ready(self):
        first = self._initiate(idempotency_key="same-key")
        asset = UploadAsset.objects.get(pk=first.data["asset_id"])
        self._put(asset)
        complete = self.client.post(f"/api/uploads/{asset.id}/complete/")
        self.assertEqual(complete.status_code, status.HTTP_200_OK, complete.data)
        second = self._initiate(idempotency_key="same-key")
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)

    def test_cancel_processing_expires(self):
        asset_id = self._initiate().data["asset_id"]
        asset = UploadAsset.objects.get(pk=asset_id)
        asset.status = UploadAssetStatus.PROCESSING
        asset.save(update_fields=["status"])
        cancel = self.client.post(f"/api/uploads/{asset_id}/cancel/")
        self.assertEqual(cancel.status_code, status.HTTP_200_OK, cancel.data)
        self.assertEqual(cancel.data["status"], UploadAssetStatus.EXPIRED)

    def test_mime_spoof_rejected(self):
        jpeg_name = {
            "purpose": "tenant_logo",
            "filename": "logo.jpg",
            "mime_type": "image/jpeg",
            "byte_size": len(_png()),
            "tenant_id": str(self.tenant.id),
        }
        response = self.client.post("/api/uploads/initiate/", jpeg_name, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        asset = UploadAsset.objects.get(pk=response.data["asset_id"])
        self._put(asset, _png())
        complete = self.client.post(f"/api/uploads/{asset.id}/complete/")
        self.assertEqual(complete.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checksum_mismatch(self):
        blob = _png()
        response = self._initiate(checksum="0" * 64, byte_size=len(blob))
        asset = UploadAsset.objects.get(pk=response.data["asset_id"])
        self._put(asset, blob)
        complete = self.client.post(f"/api/uploads/{asset.id}/complete/")
        self.assertEqual(complete.status_code, status.HTTP_400_BAD_REQUEST)

    def test_menu_initiate_requires_branch(self):
        response = self._initiate(purpose="menu_item")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_menu_initiate_with_branch(self):
        response = self._initiate(
            purpose="menu_item",
            branch_id=str(self.branch.id),
            tenant_id=str(self.tenant.id),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_storage_key_rejects_traversal(self):
        from uploads.keys import assert_safe_storage_key

        with self.assertRaises(ValueError):
            assert_safe_storage_key("../secrets")
        with self.assertRaises(ValueError):
            assert_safe_storage_key("/etc/passwd")

    def test_process_task_idempotent(self):
        from uploads.tasks import process_upload_asset

        asset_id = self._initiate().data["asset_id"]
        asset = UploadAsset.objects.get(pk=asset_id)
        self._put(asset)
        self.client.post(f"/api/uploads/{asset_id}/complete/")
        asset.refresh_from_db()
        variants = dict(asset.variant_keys)
        process_upload_asset(str(asset.id))
        asset.refresh_from_db()
        self.assertEqual(asset.status, UploadAssetStatus.READY)
        self.assertEqual(asset.variant_keys, variants)

    def test_avatar_cannot_attach_to_tenant(self):
        av = self.client.post(
            "/api/uploads/initiate/",
            {
                "purpose": "user_avatar",
                "filename": "me.png",
                "mime_type": "image/png",
                "byte_size": len(_png()),
            },
            format="json",
        )
        self.assertEqual(av.status_code, status.HTTP_201_CREATED, av.data)
        asset = UploadAsset.objects.get(pk=av.data["asset_id"])
        self._put(asset)
        self.client.post(f"/api/uploads/{asset.id}/complete/")
        response = self.client.patch(
            f"/api/tenants/{self.tenant.id}/update/",
            {
                "name": self.tenant.name,
                "status": self.tenant.status,
                "image_asset_id": str(asset.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
