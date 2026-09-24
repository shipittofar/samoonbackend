from __future__ import annotations

import logging

import boto3
from botocore.config import Config as BotoConfig
from django.conf import settings
from django.core.files.storage import default_storage
from uploads.keys import assert_safe_storage_key

logger = logging.getLogger(__name__)

# Arvan accepts canned ACL public-read on PutObject (verified 2026-09-24).
# AWS_DEFAULT_ACL is not applied by these boto3 calls.
_PUBLIC_READ_ACL = "public-read"


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


def generate_presigned_put(
    *,
    key: str,
    content_type: str,
    expires_in: int,
    public: bool = False,
) -> dict:
    key = assert_safe_storage_key(key)
    headers = {"Content-Type": content_type}
    if public:
        headers["x-amz-acl"] = _PUBLIC_READ_ACL
    client, bucket = _s3_client()
    if client is None:
        dummy = getattr(settings, "UPLOADS_DUMMY_PRESIGN_BASE", "https://upload.invalid")
        return {
            "method": "PUT",
            "url": f"{dummy}/{key}",
            "headers": headers,
            "expires_in": expires_in,
        }
    params = {
        "Bucket": bucket,
        "Key": key,
        "ContentType": content_type,
    }
    if public:
        params["ACL"] = _PUBLIC_READ_ACL
    url = client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )
    return {
        "method": "PUT",
        "url": url,
        "headers": headers,
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
    key = assert_safe_storage_key(key)
    client, bucket = _s3_client()
    if client is not None:
        from io import BytesIO

        try:
            response = client.get_object(Bucket=bucket, Key=key)
            return BytesIO(response["Body"].read())
        except Exception:
            logger.exception("Unable to open S3 object %s", key)
            raise
    return default_storage.open(key, "rb")


def save_bytes(key: str, content, content_type: str | None = None, *, public: bool = False):
    """
    Persist bytes at the canonical storage key.

    When S3 is configured, write via put_object so ContentType matches what
    complete_upload verifies via head_object. The content_type argument must be
    honored — callers (ingest/processing) already pass it.
    """
    key = assert_safe_storage_key(key)
    if hasattr(content, "seek"):
        try:
            content.seek(0)
        except Exception:
            pass

    resolved_type = content_type or getattr(content, "content_type", None) or ""
    client, bucket = _s3_client()
    if client is not None:
        if hasattr(content, "read"):
            body = content.read()
            if hasattr(content, "seek"):
                try:
                    content.seek(0)
                except Exception:
                    pass
        else:
            body = content
        params = {"Bucket": bucket, "Key": key, "Body": body}
        if resolved_type:
            params["ContentType"] = resolved_type
        if public:
            params["ACL"] = _PUBLIC_READ_ACL
        client.put_object(**params)
        return key

    if default_storage.exists(key):
        default_storage.delete(key)
    if hasattr(default_storage, "_save"):
        return default_storage._save(key, content)
    return default_storage.save(key, content)


def delete_object(key: str) -> None:
    if not key:
        return
    try:
        key = assert_safe_storage_key(key)
        client, bucket = _s3_client()
        if client is not None:
            try:
                client.delete_object(Bucket=bucket, Key=key)
            except Exception:
                logger.exception("Failed to delete S3 object %s", key)
        if default_storage.exists(key):
            default_storage.delete(key)
    except Exception:
        logger.exception("Failed to delete storage object %s", key)
