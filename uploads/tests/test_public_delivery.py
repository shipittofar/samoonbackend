from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from uploads.object_store import generate_presigned_put, save_bytes
from uploads.purposes import PURPOSE_REGISTRY


_KEY = "tenants/11111111-1111-1111-1111-111111111111/assets/22222222-2222-2222-2222-222222222222/original"
_VARIANT = "tenants/11111111-1111-1111-1111-111111111111/assets/22222222-2222-2222-2222-222222222222/variants/optimized.webp"


class PublicReadAclTests(SimpleTestCase):
    def test_registered_image_purposes_are_explicitly_public(self):
        self.assertTrue(PURPOSE_REGISTRY)
        for purpose, policy in PURPOSE_REGISTRY.items():
            self.assertTrue(
                policy.public_object,
                f"{purpose} is a storefront image and must stay anonymously readable",
            )

    def test_presigned_put_for_public_asset_signs_acl(self):
        client = MagicMock()
        client.generate_presigned_url.return_value = "https://storage.example/put"
        with patch("uploads.object_store._s3_client", return_value=(client, "samoon")):
            result = generate_presigned_put(
                key=_KEY, content_type="image/png", expires_in=60, public=True
            )
        params = client.generate_presigned_url.call_args.kwargs["Params"]
        self.assertEqual(params["ACL"], "public-read")
        self.assertEqual(params["Key"], _KEY)
        self.assertEqual(result["headers"]["x-amz-acl"], "public-read")
        self.assertEqual(result["headers"]["Content-Type"], "image/png")

    def test_presigned_put_for_private_asset_omits_acl(self):
        client = MagicMock()
        client.generate_presigned_url.return_value = "https://storage.example/put"
        with patch("uploads.object_store._s3_client", return_value=(client, "samoon")):
            result = generate_presigned_put(
                key=_KEY, content_type="image/png", expires_in=60, public=False
            )
        params = client.generate_presigned_url.call_args.kwargs["Params"]
        self.assertNotIn("ACL", params)
        self.assertNotIn("x-amz-acl", result["headers"])

    def test_save_bytes_sets_webp_content_type_and_acl_only_when_public(self):
        client = MagicMock()
        with patch("uploads.object_store._s3_client", return_value=(client, "samoon")):
            save_bytes(_VARIANT, ContentFile(b"webp"), content_type="image/webp", public=True)
            save_bytes(_KEY, ContentFile(b"jpg"), content_type="image/jpeg", public=False)
        public_call, private_call = client.put_object.call_args_list
        self.assertEqual(public_call.kwargs["ContentType"], "image/webp")
        self.assertEqual(public_call.kwargs["ACL"], "public-read")
        self.assertEqual(public_call.kwargs["Key"], _VARIANT)
        self.assertEqual(private_call.kwargs["ContentType"], "image/jpeg")
        self.assertNotIn("ACL", private_call.kwargs)


class PublicUrlShapeTests(SimpleTestCase):
    def test_public_url_uses_verified_arvan_path(self):
        """Anonymous GET on this bucket succeeds at {endpoint}/{bucket}/{key}.

        The host is already virtual-hosted (samoon.s3...), but Arvan still
        requires the bucket as a path segment. {endpoint}/{key} returns 403.
        """
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        endpoint = (settings.AWS_S3_ENDPOINT_URL or "").rstrip("/")
        if not bucket or not endpoint:
            self.skipTest("storage endpoint is not configured")
        from django.core.files.storage import default_storage

        url = default_storage.url(_VARIANT).split("?", 1)[0]
        self.assertEqual(url, f"{endpoint}/{bucket}/{_VARIANT}")
        self.assertNotIn(f"/{bucket}/{bucket}/", url)
        self.assertEqual(url.count(_VARIANT), 1)
