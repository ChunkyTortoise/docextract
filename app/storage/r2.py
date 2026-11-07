"""Cloudflare R2 storage backend using boto3 (S3-compatible API)."""
from __future__ import annotations

import boto3

from app.config import settings
from app.storage.s3 import S3StorageBackend


class R2StorageBackend(S3StorageBackend):
    _scheme = "r2"

    def __init__(self) -> None:
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
        super().__init__(client=client, bucket=settings.r2_bucket_name)
