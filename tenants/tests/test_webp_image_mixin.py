"""WebPImageMixin must not open storage for committed image keys."""
import io
import uuid
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from accounts.models import User
from tenants.models import Branch, Owner, Tenant

COMMITTED_KEY = "tenants/missing/assets/not-in-storage/original"


def make_user():
    user = User(
        id=uuid.uuid4(),
        phone_number=f"+1555{uuid.uuid4().int % 10**7:07d}",
        email=f"{uuid.uuid4().hex}@example.com",
        first_name="Test",
        last_name="User",
    )
    user.set_password("testpass123")
    user.save()
    return user


def make_branch():
    tenant = Tenant.objects.create(
        name=f"Tenant {uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
        owner=Owner.objects.create(user=make_user()),
    )
    return Branch.objects.create(tenant=tenant, name="Main")


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    return buffer.getvalue()


class WebPImageMixinSaveTests(TestCase):
    def test_committed_storage_key_is_not_opened(self):
        branch = make_branch()
        branch.image = COMMITTED_KEY
        self.assertTrue(branch.image._committed)
        self.assertIsNone(getattr(branch.image, "_file", None))

        with patch.object(branch.image.storage, "open", side_effect=AssertionError("storage.open")):
            branch.save(update_fields=["image", "updated_at"])

        branch.refresh_from_db()
        self.assertEqual(branch.image.name, COMMITTED_KEY)

    def test_missing_committed_key_still_saves(self):
        branch = make_branch()
        branch.image = COMMITTED_KEY
        branch.save(update_fields=["image", "updated_at"])
        branch.refresh_from_db()
        self.assertEqual(branch.image.name, COMMITTED_KEY)
        self.assertTrue(Branch.objects.filter(pk=branch.pk, image=COMMITTED_KEY).exists())

    def test_multipart_upload_still_converts_to_webp(self):
        branch = make_branch()
        branch.image = SimpleUploadedFile("logo.png", _png_bytes(), content_type="image/png")
        self.assertIsInstance(branch.image._file, SimpleUploadedFile)
        branch.save(update_fields=["image", "updated_at"])
        branch.refresh_from_db()
        self.assertTrue(branch.image.name.endswith(".webp"))
        self.assertNotEqual(branch.image.name, "logo.png")
