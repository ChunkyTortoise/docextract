"""Cloudflare R2 storage backend using boto3."""
from __future__ import annotations

import asyncio
import io
from functools import partial

import boto3
from botocore.exceptions import ClientError

from app.config import settings
from app.storage.base import StorageBackend


class R2StorageBackend(StorageBackend):
    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
        self._bucket = settings.r2_bucket_name

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
        return f"r2://{self._bucket}/{key}"

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
