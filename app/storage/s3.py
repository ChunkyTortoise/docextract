"""Amazon S3 storage backend using boto3.

Credentials come from boto3's default chain (on ECS Fargate that is the task
role, so no access keys are configured). The region comes from AWS_REGION /
AWS_DEFAULT_REGION, which Fargate sets on every task.

The Cloudflare R2 backend subclasses this one and only swaps the client.
"""
from __future__ import annotations

import asyncio
import io
from functools import partial

import boto3
from botocore.exceptions import ClientError

from app.config import settings
from app.storage.base import StorageBackend


class S3StorageBackend(StorageBackend):
    _scheme = "s3"

    def __init__(self, client=None, bucket: str | None = None) -> None:
        self._client = client if client is not None else boto3.client("s3")
        self._bucket = bucket if bucket is not None else settings.s3_bucket_name
        if not self._bucket:
            raise ValueError("S3_BUCKET_NAME must be set when STORAGE_BACKEND=s3")

    async def _run_sync(self, fn, *args, **kwargs):
        """Run synchronous boto3 calls in thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(fn, *args, **kwargs))

    async def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        await self._run_sync(
            self._client.upload_fileobj,
            io.BytesIO(data),
            self._bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return f"{self._scheme}://{self._bucket}/{key}"

    async def download(self, key: str) -> bytes:
        buf = io.BytesIO()
        await self._run_sync(self._client.download_fileobj, self._bucket, key, buf)
        return buf.getvalue()

    async def delete(self, key: str) -> bool:
        try:
            await self._run_sync(self._client.delete_object, Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return False
            raise

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return await self._run_sync(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def list_keys(self, prefix: str = "") -> list[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        async for page in self._paginate(paginator, Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    async def _paginate(self, paginator, **kwargs):
        loop = asyncio.get_event_loop()
        pages = await loop.run_in_executor(None, lambda: list(paginator.paginate(**kwargs)))
        for page in pages:
            yield page
