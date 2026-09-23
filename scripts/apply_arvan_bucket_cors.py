#!/usr/bin/env python
"""
Apply S3-compatible CORS on the Arvan Object Storage bucket used for direct browser PUTs.

This is storage-bucket CORS, not Django django-cors-headers.
Bucket-level APIs must use the regional endpoint
  https://s3.<region>.arvanstorage.ir
not the virtual-host object endpoint (bucket.s3.region...).

Usage (from repo root / container /app):
  python scripts/apply_arvan_bucket_cors.py
  python scripts/apply_arvan_bucket_cors.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the CORS document without calling PutBucketCors.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("ARVAN_S3_REGIONAL_ENDPOINT", "https://s3.ir-thr-at1.arvanstorage.ir"),
        help="Regional S3 endpoint for bucket APIs (default: Tehran Arvan).",
    )
    args = parser.parse_args()

    # Allow `python scripts/apply_arvan_bucket_cors.py` from /app or repo root.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "SmartRestaurant.settings")
    import django

    django.setup()

    import boto3
    from botocore.config import Config
    from django.conf import settings

    bucket = settings.AWS_STORAGE_BUCKET_NAME
    if not bucket or not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
        print("Missing ARVAN_BUCKET_NAME / ARVAN_ACCESS_KEY / ARVAN_SECRET_KEY", file=sys.stderr)
        return 1

    origins = list(settings.CORS_ALLOWED_ORIGINS)
    for required in ("http://localhost:3000", "http://127.0.0.1:3000"):
        if required not in origins:
            origins.append(required)

    cors = {
        "CORSRules": [
            {
                "AllowedOrigins": origins,
                "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
                "AllowedHeaders": ["*"],
                "ExposeHeaders": [
                    "ETag",
                    "Content-Type",
                    "Content-Length",
                    "x-amz-request-id",
                ],
                "MaxAgeSeconds": 3600,
            }
        ]
    }

    print("bucket:", bucket)
    print("endpoint:", args.endpoint)
    print("CORSConfiguration:")
    print(json.dumps(cors, indent=2))

    if args.dry_run:
        return 0

    client = boto3.client(
        "s3",
        endpoint_url=args.endpoint,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=getattr(settings, "AWS_S3_REGION_NAME", "default"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    try:
        before = client.get_bucket_cors(Bucket=bucket)
        print("before:", json.dumps(before.get("CORSRules"), indent=2))
    except Exception as exc:
        err = getattr(exc, "response", {}).get("Error", {})
        print("before:", err.get("Code") or type(exc).__name__)

    client.put_bucket_cors(Bucket=bucket, CORSConfiguration=cors)
    after = client.get_bucket_cors(Bucket=bucket)
    print("after:", json.dumps(after.get("CORSRules"), indent=2))
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
