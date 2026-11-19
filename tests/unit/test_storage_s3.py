"""Tests for the Amazon S3 storage backend (STORAGE_BACKEND=s3)."""
from __future__ import annotations

from unittest.mock import patch

import boto3
import pytest
from botocore.stub import ANY, Stubber

from app.storage.s3 import S3StorageBackend


@pytest.fixture
def stubbed():
    client = boto3.client(
        "s3",
        region_name="us-west-2",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    with Stubber(client) as stubber:
        yield S3StorageBackend(client=client, bucket="docs-bucket"), stubber


@pytest.mark.asyncio
async def test_upload_returns_s3_uri(stubbed):
    backend, stubber = stubbed
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "docs-bucket", "Key": "a/b.pdf", "Body": ANY, "ContentType": "application/pdf"},
    )
    uri = await backend.upload("a/b.pdf", b"%PDF", "application/pdf")
    assert uri == "s3://docs-bucket/a/b.pdf"


@pytest.mark.asyncio
async def test_delete_missing_key_returns_false(stubbed):
    backend, stubber = stubbed
    stubber.add_client_error("delete_object", service_error_code="NoSuchKey")
    assert await backend.delete("gone") is False


@pytest.mark.asyncio
async def test_list_keys(stubbed):
    backend, stubber = stubbed
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "p/1"}, {"Key": "p/2"}], "IsTruncated": False},
        {"Bucket": "docs-bucket", "Prefix": "p/"},
    )
    assert await backend.list_keys("p/") == ["p/1", "p/2"]


def test_missing_bucket_raises():
    with patch("app.storage.s3.settings") as s, patch("app.storage.s3.boto3"):
        s.s3_bucket_name = ""
        with pytest.raises(ValueError, match="S3_BUCKET_NAME"):
            S3StorageBackend()


@pytest.mark.asyncio
async def test_get_storage_selects_s3():
    import app.dependencies as deps

    original = deps._storage
    try:
        deps._storage = None
        with (
            patch("app.dependencies.settings") as mock_settings,
            patch("app.storage.s3.boto3"),
            patch("app.storage.s3.settings") as s3_settings,
        ):
            mock_settings.storage_backend = "s3"
            s3_settings.s3_bucket_name = "docs-bucket"
            result = await deps.get_storage()
        assert isinstance(result, S3StorageBackend)
    finally:
        deps._storage = original
