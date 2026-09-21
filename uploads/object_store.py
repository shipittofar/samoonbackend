from __future__ import annotations

import logging

import boto3
from botocore.config import Config as BotoConfig
from django.conf import settings
from django.core.files.storage import default_storage
from uploads.keys import assert_safe_storage_key

logger = logging.getLogger(__name__)


def _s3_client():
    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
    endpoint = getattr(settings, "AWS_S3_ENDPOINT_URL", None)
    access_key = getattr(settings, "AWS_ACCESS_KEY_ID", None)
    secret = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)
    if not bucket or not access_key or not secret:
        return None, None
    client_config = getattr(settings, "AWS_S3_CLIENT_CONFIG", None)
    kwargs = {
        "service_name": "s3",
        "endpoint_url": endpoint,
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret,
        "region_name": getattr(settings, "AWS_S3_REGION_NAME", "default"),
    }
    if client_config is not None:
        kwargs["config"] = client_config
    else:
        kwargs["config"] = BotoConfig(signature_version="s3v4")
    try:
        return boto3.client(**kwargs), bucket
    except Exception:
        logger.exception("Unable to create S3 client for presigned uploads")
        return None, None


def generate_presigned_put(*, key: str, content_type: str, expires_in: int) -> dict:
    key = assert_safe_storage_key(key)
    client, bucket = _s3_client()
    if client is None:
        dummy = getattr(settings, "UPLOADS_DUMMY_PRESIGN_BASE", "https://upload.invalid")
        return {
            "method": "PUT",
            "url": f"{dummy}/{key}",
            "headers": {"Content-Type": content_type},
            "expires_in": expires_in,
        }
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )
    return {
        "method": "PUT",
        "url": url,
        "headers": {"Content-Type": content_type},
        "expires_in": expires_in,
    }


def head_object(key: str) -> dict | None:
    key = assert_safe_storage_key(key)
    client, bucket = _s3_client()
    if client is not None:
        try:
            response = client.head_object(Bucket=bucket, Key=key)
            return {
                "content_length": int(response.get("ContentLength") or 0),
                "content_type": response.get("ContentType") or "",
                "etag": (response.get("ETag") or "").strip('"'),
            }
        except Exception:
            return None
    if not default_storage.exists(key):
        return None
    try:
        size = default_storage.size(key)
    except Exception:
        size = 0
    return {"content_length": size, "content_type": "", "etag": ""}


def open_object(key: str):
    return default_storage.open(assert_safe_storage_key(key), "rb")


def save_bytes(key: str, content, content_type: str | None = None):
    key = assert_safe_storage_key(key)
    if default_storage.exists(key):
        default_storage.delete(key)
    if hasattr(content, "seek"):
        try:
            content.seek(0)
        except Exception:
            pass
    if hasattr(default_storage, "_save"):
        return default_storage._save(key, content)
    return default_storage.save(key, content)


def delete_object(key: str) -> None:
    if not key:
        return
    try:
        key = assert_safe_storage_key(key)
        if default_storage.exists(key):
            default_storage.delete(key)
    except Exception:
        logger.exception("Failed to delete storage object %s", key)
